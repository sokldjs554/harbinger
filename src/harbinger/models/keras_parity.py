"""Keras(TensorFlow) 패리티 구현 — 이산시간 위험 MLP 를 다른 프레임워크로 한 번 더 구현해 결과가 일치하는지 본다.

왜 두 프레임워크인가: 모델의 본질은 "구간별 조건부 위험을 출력하고 중도절단 NLL 로 학습한다"는 명세이고,
프레임워크는 그 명세의 구현일 뿐이다. 같은 입력에서 PyTorch 와 Keras 가 비슷한 val NLL·AUROC 에 도달하면
명세가 프레임워크에 묶여 있지 않다는 증거다. 선택 의존성(`pip install .[tf]`)이며 없으면 조용히 건너뛴다.
문자 CNN 은 제외하고 수치 피처 + 범주 임베딩만 비교한다.
"""

from __future__ import annotations

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
    k = np.minimum(np.floor(tte / bin_days).astype(int), n_bins)  # n_bins 면 전 구간 생존
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


def train_keras_hazard(
    train: pd.DataFrame,
    val: pd.DataFrame,
    features: list[str],
    epochs: int = 30,
    seed: int = 0,
    verbose: int = 0,
) -> dict:
    import tensorflow as tf
    from tensorflow import keras

    tf.keras.utils.set_random_seed(seed)
    M = to_matrix(train, features)
    med = M.median()
    M = M.fillna(med)
    mean, std = M.mean(), M.std().replace(0, 1.0)

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

    num_in = keras.Input(shape=(Xn.shape[1],), name="num")
    cat_in = keras.Input(shape=(), dtype="int64", name="cat")
    arc_in = keras.Input(shape=(), dtype="int64", name="arch")
    ce = keras.layers.Flatten()(keras.layers.Embedding(len(AssetCategory), 8)(cat_in))
    ae = keras.layers.Flatten()(keras.layers.Embedding(len(ARCHETYPES), 4)(arc_in))
    h = keras.layers.Concatenate()([num_in, ce, ae])
    h = keras.layers.Dense(192, activation="gelu")(h)
    h = keras.layers.Dropout(0.2)(h)
    h = keras.layers.Dense(96, activation="gelu")(h)
    h = keras.layers.Dropout(0.2)(h)
    out = keras.layers.Dense(SURVIVAL_BINS)(h)
    model = keras.Model([num_in, cat_in, arc_in], out)

    def nll(y_true, logits):
        K = SURVIVAL_BINS
        ev, sv = y_true[:, :K], y_true[:, K:]
        log_h = tf.math.log_sigmoid(logits)
        log_1mh = tf.math.log_sigmoid(-logits)
        return -tf.reduce_mean(tf.reduce_sum(ev * log_h + sv * log_1mh, axis=1))

    model.compile(optimizer=keras.optimizers.AdamW(learning_rate=2e-3, weight_decay=1e-4), loss=nll)
    es = keras.callbacks.EarlyStopping(monitor="val_loss", patience=6, restore_best_weights=True)
    hist = model.fit(
        [Xn, Xc, Xa],
        Y,
        validation_data=([Vn, Vc, Va], VY),
        epochs=epochs,
        batch_size=1024,
        verbose=verbose,
        callbacks=[es],
    )
    logits_v = model.predict([Vn, Vc, Va], batch_size=4096, verbose=0)
    h = 1 / (1 + np.exp(-logits_v))
    p30 = np.clip(h[:, 0], 1e-6, 1 - 1e-6)
    return {
        "val_nll": float(min(hist.history["val_loss"])),
        "epochs_run": len(hist.history["loss"]),
        "p30_val": p30,
        "n_params": int(model.count_params()),
    }
