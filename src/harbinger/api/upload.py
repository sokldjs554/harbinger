"""Bounded CSV interchange; no inference or mutation before validation passes."""

from __future__ import annotations

import csv
import io
import re

import pandas as pd

from harbinger.schema import ALL_CHECK_ITEMS, AssetCategory, SiteArchetype

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
MAX_ASSETS = 500
MAX_SITES = 10
BASE = [
    "record_id",
    "record_type",
    "site_id",
    "asset_id",
    "category",
    "archetype",
    "installed",
    "criticality",
    "floor",
    "zone",
    "occurred_at",
]
INS = ["inspector_id", "overall", "memo", "dwell_seconds", "scheduled_at", "method", "photo_count"]
CHECKS = [f"chk_{c}" for c in ALL_CHECK_ITEMS]


class UploadError(ValueError):
    pass


def timestamp(value: str, *, end_of_day=False) -> pd.Timestamp:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?", str(value)):
        raise UploadError(
            "날짜는 YYYY-MM-DD 또는 시간대 없는 ISO 시각으로 입력하세요. 모든 시각은 동일한 현장 시간대여야 합니다."
        )
    try:
        ts = pd.Timestamp(value)
        if not pd.Timestamp("2000-01-01") <= ts < pd.Timestamp("2100-01-01"):
            raise ValueError()
        return ts + pd.Timedelta(hours=23, minutes=59, seconds=59) if end_of_day and len(value) == 10 else ts
    except ValueError as exc:
        raise UploadError("날짜 범위/형식 오류: 2000~2099년의 유효한 날짜가 필요합니다.") from exc


def parse_csv(content: bytes, observation_end: str):
    if len(content) > MAX_BYTES:
        raise UploadError("파일 크기 초과: UTF-8 CSV 최대 5 MiB입니다.")
    end = timestamp(observation_end, end_of_day=True)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadError("UTF-8 CSV만 지원합니다. 엑셀에서 CSV UTF-8로 저장하세요.") from exc
    try:
        reader = csv.reader(io.StringIO(text), strict=True)
        header = next(reader)
        if len(header) != len(set(header)):
            raise UploadError("중복 열 이름이 있습니다.")
        missing = set(BASE + INS) - set(header)
        if missing:
            raise UploadError("필수 열 누락: " + ", ".join(sorted(missing)))
        extra = set(header) - set(BASE + INS + CHECKS)
        if extra:
            raise UploadError("지원하지 않는 열: " + ", ".join(sorted(extra)))
        rows = []
        for rownum, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise UploadError(f"{rownum}행: 열 개수가 헤더와 다릅니다.")
            if any(len(v) > 2000 for v in row):
                raise UploadError(f"{rownum}행: 셀은 최대 2,000자입니다.")
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise UploadError("행 수 초과: 최대 20,000행입니다.")
    except (csv.Error, StopIteration) as exc:
        raise UploadError("빈 파일이거나 올바르지 않은 CSV입니다.") from exc
    if not rows:
        raise UploadError("분석할 기록이 없습니다. 헤더 아래 데이터 행을 넣으세요.")
    df = pd.DataFrame(rows, columns=header)
    for col in BASE:
        if df[col].str.strip().eq("").any():
            raise UploadError(
                f"{col}: 필수 값 누락. CSV 행 {(df.index[df[col].str.strip().eq('')] + 2).tolist()[:5]}"
            )
    for col in ["record_id", "site_id", "asset_id"]:
        if not df[col].str.fullmatch(r"[A-Za-z0-9_.-]{1,80}").all():
            raise UploadError(f"{col}: 영문/숫자/밑줄/점/하이픈 1~80자만 지원합니다.")
    if df.record_id.duplicated().any():
        raise UploadError("record_id 중복: 고유한 기록 ID를 사용하세요.")
    if df.duplicated(["asset_id", "record_type", "occurred_at"]).any():
        raise UploadError("동일 설비·기록 종류·시각 중복입니다. 원본 기록을 확인하세요.")
    if df.asset_id.nunique() > MAX_ASSETS or df.site_id.nunique() > MAX_SITES:
        raise UploadError("처리 한도 초과: 설비 500개, 고객사 10개 이하만 지원합니다.")
    for col, allowed in [
        ("category", {c.value for c in AssetCategory}),
        ("archetype", {c.value for c in SiteArchetype}),
        ("record_type", {"inspection", "breakdown", "preventive", "parts"}),
    ]:
        bad = set(df[col]) - allowed
        if bad:
            raise UploadError(f"{col}: 지원하지 않는 값 {sorted(bad)[:5]}")
    ins_mask = df.record_type.eq("inspection")
    if not ins_mask.any():
        raise UploadError("점검(inspection) 기록이 없어 우선순위를 계산할 수 없습니다.")
    for col in ["occurred_at", "installed"]:
        df[col] = df[col].map(timestamp)
    df.loc[ins_mask, "scheduled_at"] = df.loc[ins_mask, "scheduled_at"].map(timestamp)
    if (df.occurred_at > end).any():
        raise UploadError("관측 종료 이후 기록이 있습니다. 종료일 또는 기록 날짜를 확인하세요.")
    if (df.installed > df.occurred_at).any():
        raise UploadError("설치 날짜가 기록 날짜보다 늦습니다.")
    if end - df.occurred_at.min() > pd.Timedelta(days=366 * 5):
        raise UploadError("관측 기간은 최대 5년입니다.")
    for col, lo, hi, mask in [
        ("criticality", 1, 3, df.index == df.index),
        ("floor", -20, 200, df.index == df.index),
        ("overall", 0, 2, ins_mask),
        ("dwell_seconds", 0, 86400, ins_mask),
        ("photo_count", 0, 100, ins_mask),
    ]:
        values = pd.to_numeric(df.loc[mask, col], errors="coerce")
        if values.isna().any() or not values.between(lo, hi).all() or (values % 1 != 0).any():
            raise UploadError(f"{col}: {lo}~{hi} 범위의 정수가 필요합니다.")
        df.loc[mask, col] = values
    if not df.loc[ins_mask, "method"].isin(["nfc", "beacon", "manual"]).all():
        raise UploadError("method: nfc, beacon, manual만 지원합니다.")
    if not df.loc[ins_mask, "inspector_id"].str.fullmatch(r"[A-Za-z0-9_.-]{1,80}").all():
        raise UploadError("inspector_id: 점검자 ID가 필요합니다(영문/숫자/밑줄/점/하이픈).")
    asset_cols = ["site_id", "category", "installed", "criticality", "floor", "zone"]
    if (df.groupby("asset_id")[asset_cols].nunique() > 1).any().any():
        raise UploadError(
            "동일 asset_id의 설비 정보가 서로 다릅니다. 설비 ID는 고객사 전체에서 고유해야 합니다."
        )
    if (df.groupby("site_id").archetype.nunique() > 1).any():
        raise UploadError("동일 고객사의 archetype이 서로 다릅니다.")
    for col in CHECKS:
        if col not in df:
            df[col] = float("nan")
        values = pd.to_numeric(df[col].replace("", float("nan")), errors="coerce")
        if ((df[col].notna() & df[col].ne("")) & values.isna()).any() or not values.dropna().isin(
            [0, 1, 2]
        ).all():
            raise UploadError(f"{col}: 빈 값 또는 0/1/2만 지원합니다.")
        df[col] = values
    assets = df[["asset_id"] + asset_cols].drop_duplicates().copy()
    assets["name"] = assets.asset_id
    sites = df[["site_id", "archetype"]].drop_duplicates().copy()
    sites["name"] = sites.site_id
    sites["floors"] = 1
    inspections = df[ins_mask].rename(columns={"record_id": "inspection_id", "occurred_at": "performed_at"})
    inspections = inspections[
        ["inspection_id", "asset_id", "site_id"] + INS + ["performed_at"] + CHECKS
    ].copy()
    inspections["scheduled_at"] = pd.to_datetime(inspections.scheduled_at)
    inspectors = inspections[["inspector_id", "site_id"]].drop_duplicates()
    wo = df[~ins_mask][["record_id", "asset_id", "site_id", "record_type", "occurred_at", "memo"]].rename(
        columns={
            "record_id": "work_order_id",
            "record_type": "type",
            "occurred_at": "opened_at",
            "memo": "description",
        }
    )
    wo["downtime_hours"] = 0.0
    wo["severity"] = 1
    wo["closed_at"] = pd.NaT
    wo["parts_cost_krw"] = 0
    energy = pd.DataFrame(
        {
            "site_id": pd.Series(dtype=str),
            "day": pd.Series(dtype="datetime64[ns]"),
            **{
                c: pd.Series(dtype=float)
                for c in ["temp_mean_c", "occupancy_index", "electricity_kwh", "gas_m3"]
            },
        }
    )
    tables = dict(
        sites=sites,
        assets=assets,
        inspections=inspections,
        inspectors=inspectors,
        workorders=wo,
        energy=energy,
    )
    return tables, {
        "rows": len(df),
        "inspections": len(inspections),
        "workorders": len(wo),
        "assets": len(assets),
        "sites": len(sites),
        "observation_end": end.isoformat(),
        "warnings": [
            "업로드 모델은 합성 데이터로 학습했습니다. 실제 고객 검증 결과로 해석할 수 없습니다.",
            "이 형식에는 에너지 자료가 없어 에너지 피처는 결측 처리합니다.",
            "고장 기록이 누락되면 평가가 왜곡됩니다. 관측 종료일까지 모든 고장을 포함해야 합니다.",
        ],
    }


def export_example(tables, site_id: str, observation_end: pd.Timestamp) -> bytes:
    assets = tables["assets"].query("site_id == @site_id")
    metadata = assets[["asset_id", "site_id", "category", "installed", "criticality", "floor", "zone"]].merge(
        tables["sites"][["site_id", "archetype"]], on="site_id"
    )
    ins = (
        tables["inspections"]
        .query("site_id == @site_id")
        .rename(columns={"inspection_id": "record_id", "performed_at": "occurred_at"})
        .copy()
    )
    ins["record_type"] = "inspection"
    wo = (
        tables["workorders"]
        .query("site_id == @site_id")
        .rename(
            columns={
                "work_order_id": "record_id",
                "opened_at": "occurred_at",
                "type": "record_type",
                "description": "memo",
            }
        )
        .copy()
    )
    events = pd.concat([ins, wo], ignore_index=True)
    events = events.loc[pd.to_datetime(events["occurred_at"]) <= observation_end].copy()
    events = events.drop(columns=[c for c in metadata if c != "asset_id" and c in events]).merge(
        metadata, on="asset_id"
    )
    for c in INS + CHECKS:
        if c not in events:
            events[c] = ""
    return events[BASE + INS + CHECKS].sort_values("occurred_at").to_csv(index=False).encode("utf-8-sig")
