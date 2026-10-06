"""문서용 그림 — artifacts/*.json 에서 matplotlib PNG 를 만든다 (docs/images). 팔레트는 dataviz 레퍼런스 인스턴스(라이트)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

BLUE, ORANGE, AQUA, DEEMPH, GRID, INK, MUTED, RED = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#c3c2b7",
    "#e1e0d9",
    "#0b0b0b",
    "#898781",
    "#e34948",
)
import os  # noqa: E402

from matplotlib import font_manager  # noqa: E402

# 한글 폰트: HARBINGER_FONT_FILE 로 지정한 TTF 를 등록하거나, 설치된 한글 지원 폰트 중 하나를 고른다.
_font_file = os.environ.get("HARBINGER_FONT_FILE")
if _font_file and Path(_font_file).exists():
    font_manager.fontManager.addfont(_font_file)
_KO_CANDIDATES = [
    "NanumGothic",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "AppleGothic",
    "Malgun Gothic",
    "WenQuanYi Zen Hei",
    "Unifont",
]
_installed = {f.name for f in font_manager.fontManager.ttflist}
_FAMILY = [f for f in _KO_CANDIDATES if f in _installed] + ["DejaVu Sans"]
plt.rcParams.update(
    {
        "font.family": ["NanumGothic", "Noto Sans CJK KR", "AppleGothic", "Malgun Gothic", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "font.size": 10,
        "axes.edgecolor": DEEMPH,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "#fcfcfb",
        "axes.facecolor": "#fcfcfb",
    }
)
plt.rcParams["font.family"] = _FAMILY
plt.rcParams["axes.axisbelow"] = True


def _load(d: Path, name: str):
    p = d / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def fig_ablation(art: Path, out: Path) -> None:
    a = _load(art, "ablation")
    base = _load(art, "metrics")["baselines"]
    if not a:
        return
    order = ["checklist_only", "+text", "+text+quality", "+text+quality+history", "full(+energy)"]
    labels = ["체크리스트만", "+메모 텍스트", "+점검 품질", "+고장 이력", "+에너지(전체)"]
    vals = [a[k]["auroc"] for k in order]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    y = np.arange(len(order))
    ax.barh(y, vals, color=BLUE, height=0.55)
    for yi, v in zip(y, vals):
        ax.text(v + 0.004, yi, f"{v:.3f}", va="center", color=INK, fontsize=9)
    ax.axvline(base["oracle_latent_state"]["auroc"], color=DEEMPH, lw=1)
    ax.text(
        base["oracle_latent_state"]["auroc"] + 0.003,
        len(order) - 0.6,
        f"오라클(숨은 상태) {base['oracle_latent_state']['auroc']:.3f}",
        color=MUTED,
        fontsize=8,
    )
    ax.axvline(base["last_inspection"]["auroc"], color=DEEMPH, lw=1, ls="-")
    ax.text(
        base["last_inspection"]["auroc"] + 0.003,
        -0.45,
        f"마지막 점검만 {base['last_inspection']['auroc']:.3f}",
        color=MUTED,
        fontsize=8,
    )
    ax.set_yticks(y, labels)
    ax.set_xlim(0.5, max(vals + [base["oracle_latent_state"]["auroc"]]) + 0.06)
    ax.set_xlabel("AUROC — 30일 내 비계획 고장 (테스트 기간)")
    ax.set_title("피처 그룹을 더해 갈 때", loc="left", color=INK, fontsize=11)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(out / "ablation.png", dpi=160)
    plt.close(fig)


def fig_patrol(art: Path, out: Path) -> None:
    p = _load(art, "patrol")
    if not p:
        return
    m = p["methods"]
    order = [
        k
        for k in ["round_robin", "random", "age", "last_inspection", "harbinger_hgb", "harbinger_deep"]
        if k in m
    ]
    labels = {
        "round_robin": "라운드로빈(가장 오래 안 본 순)",
        "random": "무작위",
        "age": "연식순",
        "last_inspection": "마지막 점검 판정순",
        "harbinger_hgb": "harbinger (HGB)",
        "harbinger_deep": "harbinger (위험 네트)",
    }
    vals = [m[k]["precision_at_k"] for k in order]
    colors = [BLUE if k.startswith("harbinger") else DEEMPH for k in order]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    y = np.arange(len(order))
    ax.barh(y, vals, color=colors, height=0.55)
    for yi, v in zip(y, vals):
        ax.text(v + 0.003, yi, f"{v:.1%}", va="center", color=INK, fontsize=9)
    ax.set_yticks(y, [labels[k] for k in order])
    ax.set_xlabel(f"상위 {p['k']}개 중 30일 내 실제 고장 비율 (사이트·날 평균, {p['days']}일 × 사이트)")
    ax.set_title(
        f"오늘 순찰 목록의 적중률 — 기본 고장률 {p['base_rate']:.1%}", loc="left", color=INK, fontsize=11
    )
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(out / "patrol.png", dpi=160)
    plt.close(fig)


def fig_calibration(art: Path, out: Path) -> None:
    c = _load(art, "calibration")
    if not c:
        return
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    mx = (
        max([r["pred_mean"] for r in c["calibrated"]] + [r["obs_rate"] for r in c["calibrated"]] + [0.05])
        * 1.1
    )
    ax.plot([0, mx], [0, mx], color=DEEMPH, lw=1)
    for key, color, label in (
        ("uncalibrated", ORANGE, f"캘리브레이션 전 (ECE {c['ece_uncalibrated']:.3f})"),
        ("calibrated", BLUE, f"isotonic 후 (ECE {c['ece_calibrated']:.3f})"),
    ):
        xs = [r["pred_mean"] for r in c[key]]
        ys = [r["obs_rate"] for r in c[key]]
        ax.plot(xs, ys, color=color, lw=2, marker="o", ms=5, mec="#fcfcfb", mew=1.5, label=label)
    ax.set_xlabel("예측 확률 (분위 구간 평균)")
    ax.set_ylabel("실제 30일 고장률")
    ax.set_xlim(0, mx)
    ax.set_ylim(0, mx)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.set_title("신뢰도 다이어그램 (테스트)", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "calibration.png", dpi=160)
    plt.close(fig)


def fig_loso(art: Path, out: Path) -> None:
    lo = _load(art, "loso")
    if not lo or not lo.get("mean_by_months"):
        return
    months = [int(m) for m in lo["mean_by_months"]]
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.2))
    # 사이트 상수 오프셋은 사이트 내 순위를 바꾸지 않아 AUROC 는 정의상 같다 — 확률 척도 지표(Brier·ECE)만 그린다
    for ax, key, title in zip(axes, ("brier", "ece"), ("Brier (낮을수록 좋음)", "ECE (낮을수록 좋음)")):
        vals = [lo["mean_by_months"][str(m)][key] for m in months]
        ax.plot(
            months,
            vals,
            color=BLUE,
            lw=2,
            marker="o",
            ms=6,
            mec="#fcfcfb",
            mew=1.5,
            label="보류 사이트 (pooled + 오프셋)",
        )
        warm = np.nanmean([v["warm_in_sample_site"][key] for v in lo["per_site"].values()])
        ax.axhline(warm, color=DEEMPH, lw=1)
        ax.text(
            months[-1],
            warm,
            " 그 사이트를 포함해 학습(warm)",
            color=MUTED,
            fontsize=8,
            va="bottom",
            ha="right",
        )
        ax.set_xticks(months)
        ax.set_xlabel("신규 사이트 자체 데이터 (개월)")
        ax.set_title(title, loc="left", color=INK, fontsize=10)
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.suptitle(
        f"콜드스타트 — leave-one-site-out, 보류 {len(lo['per_site'])}개 사이트 평균",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out / "loso.png", dpi=160)
    plt.close(fig)


def fig_importance(art: Path, out: Path) -> None:
    imp = _load(art, "importance")
    if not imp:
        return
    top = imp[:15]
    group_color = {
        "tx": ORANGE,
        "ck": BLUE,
        "wo": AQUA,
        "q": "#4a3aa7",
        "en": "#eda100",
        "st": DEEMPH,
        "se": DEEMPH,
    }
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    y = np.arange(len(top))
    ax.barh(
        y,
        [t["mean_abs_shap"] for t in top],
        color=[group_color.get(t["feature"].split("_")[0], DEEMPH) for t in top],
        height=0.6,
    )
    ax.set_yticks(y, [t["label"] for t in top])
    ax.invert_yaxis()
    ax.set_xlabel("mean |SHAP| (로그오즈)")
    ax.set_title("무엇이 확률을 움직이는가 — 상위 15 피처", loc="left", color=INK, fontsize=11)
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(color=c, label=lab)
            for c, lab in (
                (ORANGE, "메모 텍스트"),
                (BLUE, "체크리스트"),
                (AQUA, "고장 이력"),
                ("#4a3aa7", "점검 품질"),
                ("#eda100", "에너지"),
                (DEEMPH, "정적·계절"),
            )
        ],
        frameon=False,
        fontsize=8,
        loc="lower right",
    )
    fig.tight_layout()
    fig.savefig(out / "importance.png", dpi=160)
    plt.close(fig)


def fig_survival(art: Path, out: Path) -> None:
    s = _load(art, "survival")
    if not s:
        return
    rows = []
    for k, v in s["lifelines"].items():
        if "c_index" in v:
            rows.append((k, v["c_index"], v.get("ibs")))
    for k, v in s["deep"].items():
        rows.append((f"deep {k}", v["c_index"], v.get("ibs")))
    if not rows:
        return
    names = {
        "cox": "Cox PH",
        "aft": "Weibull AFT",
        "hgb_constant_hazard": "HGB P30 → 일정위험",
        "deep text+site": "위험 네트 (메모+사이트)",
        "deep notext+site": "위험 네트 (메모 없음)",
        "deep text+nosite": "위험 네트 (사이트 없음)",
    }
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.2))
    y = np.arange(len(rows))
    axes[0].barh(y, [r[1] for r in rows], color=BLUE, height=0.55)
    axes[0].set_yticks(y, [names.get(r[0], r[0]) for r in rows])
    axes[0].set_xlim(0.5, max(r[1] for r in rows) + 0.05)
    axes[0].set_title("C-index (높을수록 좋음)", loc="left", color=INK, fontsize=10)
    axes[0].invert_yaxis()
    axes[1].barh(y, [r[2] or 0 for r in rows], color=BLUE, height=0.55)
    axes[1].set_yticks(y, [""] * len(rows))
    axes[1].set_title("IBS 30~360일 (낮을수록 좋음)", loc="left", color=INK, fontsize=10)
    axes[1].invert_yaxis()
    for ax, idx, fmt in ((axes[0], 1, "{:.3f}"), (axes[1], 2, "{:.4f}")):
        for yi, r in zip(y, rows):
            if r[idx] is not None:
                ax.text(
                    r[idx] + (0.003 if idx == 1 else 0.0005),
                    yi,
                    fmt.format(r[idx]),
                    va="center",
                    color=INK,
                    fontsize=8,
                )
    fig.tight_layout()
    fig.savefig(out / "survival.png", dpi=160)
    plt.close(fig)


def fig_energy(data: Path, art: Path, out: Path, models: Path = Path("models")) -> None:
    """한 사이트의 여름 전기 실측/기대치 예시 — 번들의 에너지 모델로 그린다."""
    try:
        import pandas as pd

        from harbinger.models.registry import load_bundle

        b = load_bundle(models)
        en = pd.read_parquet(data / "energy.parquet")
        sid = sorted(en["site_id"].unique())[0]
        g = en[(en["site_id"] == sid)].sort_values("day")
        g = g[g["day"] >= g["day"].max() - pd.Timedelta(days=150)]
        an = b["energy"].anomalies(g)
        fig, ax = plt.subplots(figsize=(8.4, 3.2))
        ax.plot(an["day"], an[b["energy"].target], color=BLUE, lw=2, label="실측 kWh")
        ax.plot(an["day"], an["yhat"], color=DEEMPH, lw=2, label="기대치 (회귀)")
        bad = an[an["anomaly"]]
        ax.scatter(
            bad["day"],
            bad[b["energy"].target],
            color=RED,
            s=28,
            zorder=5,
            edgecolor="#fcfcfb",
            linewidth=1.5,
            label=f"이상일 z>2.5 ({len(bad)}일)",
        )
        ax.legend(frameon=False, fontsize=8, loc="upper left")
        ax.set_title(
            f"{sid} — 날씨·재실을 감안한 기대 전기사용량과 잔차 이상", loc="left", color=INK, fontsize=11
        )
        ax.set_ylabel("kWh/일")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(out / "energy.png", dpi=160)
        plt.close(fig)
    except Exception as e:  # 번들이 없으면 건너뛴다
        print(f"[figures] energy skipped: {e!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("docs/images"))
    ap.add_argument("--models", type=Path, default=Path("models"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for f in (fig_ablation, fig_patrol, fig_calibration, fig_loso, fig_importance, fig_survival):
        f(a.artifacts, a.out)
    fig_energy(a.data, a.artifacts, a.out, a.models)
    print("figures:", sorted(p.name for p in a.out.glob("*.png")))


if __name__ == "__main__":
    main()
