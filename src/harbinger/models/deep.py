"""PyTorch 이산시간 위험 네트워크 — 수치 피처 + 범주 임베딩 + 사이트 임베딩(드롭아웃) + 메모 문자 CNN.

출력: 30일 구간 K=12 개의 조건부 위험 h_k. S(t_k) = Π_{j≤k}(1−h_j), P30 = h_0.
사이트 임베딩은 학습 중 확률 p 로 '미지 사이트(0)' 로 치환해 신규 고객사(콜드스타트)에서도 동작하게 한다.
메모 인코더는 외부 사전학습 모델 없이 문자 단위로 처음부터 학습한다(배포 환경에 모델 다운로드 의존 없음).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

from harbinger.config import SURVIVAL_BIN_DAYS, SURVIVAL_BINS
from harbinger.models.common import to_matrix
from harbinger.schema import AssetCategory

ARCHETYPES = ("gov_office", "hospital", "hotel", "office")
MAX_CHARS = 64


class CharVocab:
    def __init__(self, texts: list[str] | None = None, min_count: int = 3):
        self.itos = ["<pad>", "<unk>"]
        if texts is not None:
            counts: dict[str, int] = {}
            for t in texts:
                for ch in t:
                    counts[ch] = counts.get(ch, 0) + 1
            self.itos += sorted([c for c, n in counts.items() if n >= min_count])
        self.stoi = {c: i for i, c in enumerate(self.itos)}

    def encode(self, text: str) -> list[int]:
        ids = [self.stoi.get(ch, 1) for ch in (text or "")[:MAX_CHARS]]
        return ids + [0] * (MAX_CHARS - len(ids))

    def to_json(self) -> str:
        return json.dumps(self.itos, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> CharVocab:
        v = cls()
        v.itos = json.loads(s)
        v.stoi = {c: i for i, c in enumerate(v.itos)}
        return v


class HazardNet(nn.Module):
    def __init__(
        self,
        n_num: int,
        n_sites: int,
        vocab_size: int,
        use_text: bool = True,
        use_site: bool = True,
        hidden: int = 192,
        dropout: float = 0.2,
        n_bins: int = SURVIVAL_BINS,
    ):
        super().__init__()
        self.use_text, self.use_site = use_text, use_site
        self.cat_emb = nn.Embedding(len(AssetCategory), 8)
        self.arch_emb = nn.Embedding(len(ARCHETYPES), 4)
        self.site_emb = nn.Embedding(n_sites + 1, 8)  # 0 = 미지 사이트
        d_in = n_num + 8 + 4 + (8 if use_site else 0)
        if use_text:
            self.char_emb = nn.Embedding(vocab_size, 32, padding_idx=0)
            self.convs = nn.ModuleList([nn.Conv1d(32, 48, k, padding=k // 2) for k in (2, 3, 5)])
            d_in += 48 * 3
        self.trunk = nn.Sequential(
            nn.Linear(d_in, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, n_bins),
        )

    def forward(self, num, cat, arch, site, chars):
        parts = [num, self.cat_emb(cat), self.arch_emb(arch)]
        if self.use_site:
            parts.append(self.site_emb(site))
        if self.use_text:
            e = self.char_emb(chars).transpose(1, 2)  # B × 32 × L
            feats = [torch.relu(conv(e)).amax(dim=2) for conv in self.convs]
            parts.extend(feats)
        logits = self.trunk(torch.cat(parts, dim=1))
        return logits  # 구간별 위험 로짓

    def hazards(self, *args):
        return torch.sigmoid(self.forward(*args))


def discrete_nll(
    logits: torch.Tensor, tte_days: torch.Tensor, event: torch.Tensor, bin_days: int = SURVIVAL_BIN_DAYS
) -> torch.Tensor:
    """이산시간 생존 NLL. 사건 구간 k: −log h_k − Σ_{j<k} log(1−h_j). 중도절단: −Σ_{j<k} log(1−h_j) (k 구간은 부분 관측이라 제외)."""
    K = logits.shape[1]
    k = torch.clamp((tte_days / bin_days).floor().long(), 0, K - 1)
    beyond = (tte_days / bin_days).floor().long() >= K  # 마지막 구간 이후 — 전 구간 생존으로 처리
    log_h = nn.functional.logsigmoid(logits)
    log_1mh = nn.functional.logsigmoid(-logits)
    ar = torch.arange(K, device=logits.device).unsqueeze(0)
    before = (ar < k.unsqueeze(1)).float()
    surv_term = (log_1mh * before).sum(dim=1)
    ev = event.float() * (~beyond).float()
    event_term = ev * log_h.gather(1, k.unsqueeze(1)).squeeze(1)
    all_surv = log_1mh.sum(dim=1)
    nll = -(torch.where(beyond, all_surv, surv_term + event_term))
    return nll.mean()


@dataclass
class DeepBundle:
    model: HazardNet
    features: list[str]
    medians: pd.Series
    means: pd.Series
    stds: pd.Series
    vocab: CharVocab
    site_index: dict[str, int]
    use_text: bool = True
    use_site: bool = True
    meta: dict = field(default_factory=dict)

    def tensors(
        self,
        X: pd.DataFrame,
        train_mode: bool = False,
        site_dropout: float = 0.0,
        rng: np.random.Generator | None = None,
    ):
        M = to_matrix(X, self.features).fillna(self.medians)
        Z = ((M - self.means) / self.stds.replace(0, 1.0)).to_numpy(dtype=np.float32)
        cat = (
            X["st_category"]
            .astype(str)
            .map({c.value: i for i, c in enumerate(AssetCategory)})
            .fillna(0)
            .to_numpy(dtype=np.int64)
        )
        arch = (
            X["st_archetype"]
            .astype(str)
            .map({a: i for i, a in enumerate(ARCHETYPES)})
            .fillna(0)
            .to_numpy(dtype=np.int64)
        )
        site = X["site_id"].map(self.site_index).fillna(0).to_numpy(dtype=np.int64)
        if train_mode and site_dropout > 0 and rng is not None:
            site = np.where(rng.random(len(site)) < site_dropout, 0, site)
        chars = np.array([self.vocab.encode(m) for m in X["memo"].fillna("").astype(str)], dtype=np.int64)
        return (
            torch.from_numpy(Z),
            torch.from_numpy(cat),
            torch.from_numpy(arch),
            torch.from_numpy(site),
            torch.from_numpy(chars),
        )

    @torch.no_grad()
    def hazards(self, X: pd.DataFrame, batch: int = 4096) -> np.ndarray:
        self.model.eval()
        out = []
        for i in range(0, len(X), batch):
            tt = self.tensors(X.iloc[i : i + batch])
            out.append(self.model.hazards(*tt).numpy())
        return np.concatenate(out) if out else np.zeros((0, SURVIVAL_BINS))

    def survival_curve(self, X: pd.DataFrame) -> np.ndarray:
        h = self.hazards(X)
        return np.cumprod(1 - h, axis=1)

    def p_fail_within(self, X: pd.DataFrame, days: int = 30) -> np.ndarray:
        S = self.survival_curve(X)
        k = max(0, min(SURVIVAL_BINS - 1, int(math.ceil(days / SURVIVAL_BIN_DAYS)) - 1))
        return np.clip(1 - S[:, k], 1e-6, 1 - 1e-6)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.p_fail_within(X, 30)


def train_deep(
    train: pd.DataFrame,
    val: pd.DataFrame,
    features: list[str],
    use_text: bool = True,
    use_site: bool = True,
    epochs: int = 40,
    batch: int = 1024,
    lr: float = 2e-3,
    site_dropout: float = 0.3,
    seed: int = 0,
    verbose: bool = True,
    patience: int = 6,
) -> DeepBundle:
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    rng = np.random.default_rng(seed)
    M = to_matrix(train, features)
    medians = M.median()
    M = M.fillna(medians)
    means, stds = M.mean(), M.std().replace(0, 1.0)
    vocab = CharVocab(train["memo"].fillna("").astype(str).tolist())
    sites = sorted(train["site_id"].unique())
    site_index = {s: i + 1 for i, s in enumerate(sites)}
    model = HazardNet(len(features), len(sites), len(vocab.itos), use_text=use_text, use_site=use_site)
    bundle = DeepBundle(model, features, medians, means, stds, vocab, site_index, use_text, use_site)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    tr_t = bundle.tensors(train, train_mode=True, site_dropout=site_dropout, rng=rng)
    y_t = torch.from_numpy(train["tte_days"].to_numpy(dtype=np.float32))
    e_t = torch.from_numpy(train["event"].to_numpy(dtype=np.int64))
    va_t = bundle.tensors(val)
    y_v = torch.from_numpy(val["tte_days"].to_numpy(dtype=np.float32))
    e_v = torch.from_numpy(val["event"].to_numpy(dtype=np.int64))
    n = len(train)
    best, best_state, bad = float("inf"), None, 0
    history = []
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        # 사이트 드롭아웃은 에포크마다 다시 뽑는다
        site_col = tr_t[3].clone()
        if use_site and site_dropout > 0:
            mask = torch.from_numpy(rng.random(n) < site_dropout)
            site_col[mask] = 0
        tot = 0.0
        for i in range(0, n, batch):
            idx = perm[i : i + batch]
            logits = model(tr_t[0][idx], tr_t[1][idx], tr_t[2][idx], site_col[idx], tr_t[4][idx])
            loss = discrete_nll(logits, y_t[idx], e_t[idx])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            opt.step()
            tot += float(loss) * len(idx)
        sched.step()
        model.eval()
        with torch.no_grad():
            vl = float(discrete_nll(model(*va_t), y_v, e_v)) if len(val) else tot / n
        history.append({"epoch": ep + 1, "train_nll": tot / n, "val_nll": vl})
        if verbose and (ep % 5 == 0 or ep == epochs - 1):
            print(
                f"[deep:{'text' if use_text else 'notext'}{'' if use_site else ',nosite'}] epoch {ep + 1} train={tot / n:.4f} val={vl:.4f}"
            )
        if vl < best - 1e-4:
            best, bad = vl, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    bundle.meta = {
        "best_val_nll": best,
        "epochs_run": len(history),
        "history": history,
        "n_params": sum(p.numel() for p in model.parameters()),
    }
    return bundle


def save_deep(bundle: DeepBundle, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    torch.save(bundle.model.state_dict(), path / "hazardnet.pt")
    (path / "deep_meta.json").write_text(
        json.dumps(
            {
                "features": bundle.features,
                "medians": bundle.medians.to_dict(),
                "means": bundle.means.to_dict(),
                "stds": bundle.stds.to_dict(),
                "vocab": bundle.vocab.itos,
                "site_index": bundle.site_index,
                "use_text": bundle.use_text,
                "use_site": bundle.use_site,
                "meta": {k: v for k, v in bundle.meta.items() if k != "history"},
            },
            ensure_ascii=False,
        )
    )


def load_deep(path: Path) -> DeepBundle:
    m = json.loads((path / "deep_meta.json").read_text())
    vocab = CharVocab()
    vocab.itos = m["vocab"]
    vocab.stoi = {c: i for i, c in enumerate(vocab.itos)}
    model = HazardNet(
        len(m["features"]),
        len(m["site_index"]),
        len(vocab.itos),
        use_text=m["use_text"],
        use_site=m["use_site"],
    )
    model.load_state_dict(torch.load(path / "hazardnet.pt", map_location="cpu"))
    model.eval()
    return DeepBundle(
        model,
        m["features"],
        pd.Series(m["medians"]),
        pd.Series(m["means"]),
        pd.Series(m["stds"]),
        vocab,
        m["site_index"],
        m["use_text"],
        m["use_site"],
        m["meta"],
    )
