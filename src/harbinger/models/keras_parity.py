"""Keras(TensorFlow) 패리티 구현 — 이산시간 위험 MLP 를 다른 프레임워크로 한 번 더 구현해 결과가 일치하는지 본다.

동일 가중치에서 출력·손실·기울기를 대조하고, 별도로 실제 학습 결과를 기록한다.
같은 정수 시드가 같은 초기화/배치/드롭아웃을 뜻하지 않으므로 독립 학습의 성능 동등성을 보장하지 않는다.
선택 의존성(`pip install .[tf]`)이며 일반 환경에 없으면 검사를 건너뛰지만 CI의 전용 작업은 설치를 요구한다.
문자 CNN·사이트 임베딩은 제외한다. 수치 메모 특징은 유지하므로 메모 제거 실험이 아니다.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from harbinger.config import SURVIVAL_BIN_DAYS, SURVIVAL_BINS
from harbinger.models.common import to_matrix
from harbinger.schema import AssetCategory

ARCHETYPES = ("gov_office", "hospital", "hotel", "office")


def tf_available() -> bool:
    """TensorFlow 설치 여부 — import 하지 않고 확인한다. 같은 프로세스에 TF 와 torch 를 함께 올리면
    torch 옵티마이저 초기화(_dynamo import)에서 세그폴트가 날 수 있어, 패리티 검사는 항상 별도 프로세스에서 돌린다."""
    import importlib.util

    return importlib.util.find_spec("tensorflow") is not None


def _targets(
    tte: np.ndarray, event: np.ndarray, n_bins: int = SURVIVAL_BINS, bin_days: int = SURVIVAL_BIN_DAYS
) -> np.ndarray:
    """(n, 2K): 앞 K 는 '구간 j 에서 사건' 마스크, 뒤 K 는 '구간 j 생존 관측' 마스크 — 손실을 마스크 곱으로 계산한다."""
    # Events are in (left, right]; censored rows contribute complete bins only.
    scaled = tte / bin_days
    k = np.clip(np.where(event, np.ceil(scaled) - 1, np.floor(scaled)).astype(int), 0, n_bins)
    ev = np.zeros((len(tte), n_bins), dtype=np.float32)
    sv = np.zeros((len(tte), n_bins), dtype=np.float32)
    for i in range(len(tte)):
        kk = int(k[i])
        if kk >= n_bins:
            sv[i, :] = 1.0
        else:
            sv[i, :kk] = 1.0
            if event[i]:
                ev[i, kk] = 1.0
    return np.concatenate([ev, sv], axis=1)


def discrete_hazard_nll(y_true, logits):
    """TensorFlow loss for event/survival masks; supports any bin count."""
    import tensorflow as tf

    n_bins = tf.shape(logits)[-1]
    ev, sv = y_true[:, :n_bins], y_true[:, n_bins:]
    return -tf.reduce_mean(
        tf.reduce_sum(ev * tf.math.log_sigmoid(logits) + sv * tf.math.log_sigmoid(-logits), axis=1)
    )


def build_keras_hazard(n_features: int, initial_weights: dict | None = None):
    """Build the no-CNN/no-site comparison network, optionally with common initial weights."""
    from tensorflow import keras

    num_in = keras.Input(shape=(n_features,), name="num")
    cat_in = keras.Input(shape=(), dtype="int64", name="cat")
    arc_in = keras.Input(shape=(), dtype="int64", name="arch")
    ce = keras.layers.Flatten()(keras.layers.Embedding(len(AssetCategory), 8, name="category")(cat_in))
    ae = keras.layers.Flatten()(keras.layers.Embedding(len(ARCHETYPES), 4, name="archetype")(arc_in))
    h = keras.layers.Concatenate()([num_in, ce, ae])
    h = keras.layers.Dense(192, activation="gelu", name="hidden1")(h)
    h = keras.layers.Dropout(0.2)(h)
    h = keras.layers.Dense(96, activation="gelu", name="hidden2")(h)
    h = keras.layers.Dropout(0.2)(h)
    out = keras.layers.Dense(SURVIVAL_BINS, name="hazard")(h)
    model = keras.Model([num_in, cat_in, arc_in], out)
    if initial_weights is not None:
        for name in ("category", "archetype"):
            model.get_layer(name).set_weights([initial_weights[name]])
        for name in ("hidden1", "hidden2", "hazard"):
            model.get_layer(name).set_weights(initial_weights[name])
    return model


def train_keras_hazard(
    train: pd.DataFrame,
    val: pd.DataFrame,
    features: list[str],
    epochs: int = 30,
    seed: int = 0,
    verbose: int = 0,
    initial_weights: dict | None = None,
) -> dict:
    import tensorflow as tf
    from tensorflow import keras

    tf.keras.utils.set_random_seed(seed)
    M = to_matrix(train, features)
    med = M.median().fillna(0)
    M = M.fillna(med)
    mean, std = M.mean(), M.std().replace(0, 1.0).fillna(1.0)

    def prep(X: pd.DataFrame) -> np.ndarray:
        return ((to_matrix(X, features).fillna(med) - mean) / std).to_numpy(dtype=np.float32)

    cat_ix = {c.value: i for i, c in enumerate(AssetCategory)}
    arc_ix = {a: i for i, a in enumerate(ARCHETYPES)}

    def enc(X: pd.DataFrame):
        return (
            prep(X),
            X["st_category"].astype(str).map(cat_ix).fillna(0).to_numpy(np.int64),
            X["st_archetype"].astype(str).map(arc_ix).fillna(0).to_numpy(np.int64),
        )

    Xn, Xc, Xa = enc(train)
    Vn, Vc, Va = enc(val)
    Y = _targets(train["tte_days"].to_numpy(), train["event"].to_numpy())
    VY = _targets(val["tte_days"].to_numpy(), val["event"].to_numpy())

    model = build_keras_hazard(Xn.shape[1], initial_weights=initial_weights)

    model.compile(
        optimizer=keras.optimizers.AdamW(
            learning_rate=2e-3, weight_decay=1e-4, global_clipnorm=2.0, epsilon=1e-8
        ),
        loss=discrete_hazard_nll,
    )
    es = keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=6, min_delta=1e-4, restore_best_weights=True
    )
    schedule = keras.callbacks.LearningRateScheduler(
        lambda epoch: 2e-3 * (1 + math.cos(math.pi * epoch / epochs)) / 2
    )
    hist = model.fit(
        [Xn, Xc, Xa],
        Y,
        validation_data=([Vn, Vc, Va], VY),
        epochs=epochs,
        batch_size=1024,
        verbose=verbose,
        callbacks=[es, schedule],
    )
    logits_v = model.predict([Vn, Vc, Va], batch_size=4096, verbose=0)
    h = 1 / (1 + np.exp(-logits_v))
    p30 = np.clip(h[:, 0], 1e-6, 1 - 1e-6)
    return {
        "val_nll": float(min(hist.history["val_loss"])),
        "epochs_run": len(hist.history["loss"]),
        "p30_val": p30,
        "n_params": int(model.count_params()),
        "learning_rates": [float(v) for v in hist.history["learning_rate"]],
    }
