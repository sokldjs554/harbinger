import pandas as pd
import pytest

from harbinger.api.upload import UploadError, parse_csv

HEADER = "record_id,record_type,site_id,asset_id,category,archetype,installed,criticality,floor,zone,occurred_at,inspector_id,overall,memo,dwell_seconds,scheduled_at,method,photo_count\n"
ROW = "i1,inspection,client-a,pump-1,pump,office,2020-01-01,2,1,A,2025-08-01,person-1,1,약간 소음,60,2025-08-01,nfc,0\n"


def test_csv_roundtrip_and_optional_memo():
    tables, summary = parse_csv((HEADER + ROW).encode(), "2025-10-01")
    assert len(tables["inspections"]) == 1
    assert summary["observation_end"] == "2025-10-01T23:59:59"
    assert tables["workorders"].empty
    assert tables["inspections"].iloc[0].memo == "약간 소음"


@pytest.mark.parametrize(
    "text, message",
    [
        ("bad\n1", "필수 열"),
        (HEADER + ROW + ROW, "중복"),
        (HEADER + ROW.replace("2025-08-01", "wrong"), "날짜"),
        (HEADER + ROW.replace(",1,약간", ",9,약간"), "overall"),
        (HEADER + ROW.replace(",pump,", ",unknown,"), "category"),
        (HEADER + ROW.replace("60,2025", "-1,2025"), "dwell_seconds"),
    ],
)
def test_invalid_csv_has_actionable_error(text, message):
    with pytest.raises(UploadError, match=message):
        parse_csv(text.encode(), "2025-10-01")


def test_no_future_records_or_silent_dedup():
    with pytest.raises(UploadError, match="관측 종료"):
        parse_csv((HEADER + ROW).encode(), "2025-07-01")


def test_conflicting_asset_metadata():
    row2 = ROW.replace("i1,", "i2,").replace("2025-08-01", "2025-08-02").replace(",2,1,A,", ",3,1,A,")
    with pytest.raises(UploadError, match="설비 정보"):
        parse_csv((HEADER + ROW + row2).encode(), "2025-10-01")


def test_raw_text_is_not_executed_or_interpreted():
    tables, _ = parse_csv(
        (HEADER + ROW.replace("약간 소음", "<script>alert(1)</script>")).encode(), "2025-10-01"
    )
    assert "<script>" in tables["inspections"].iloc[0].memo
    assert pd.api.types.is_datetime64_any_dtype(tables["inspections"].performed_at)


def test_shared_example_mutation_disabled_by_default():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from harbinger.api.routers.risk import ingest
    from harbinger.config import Settings

    store = SimpleNamespace(settings=Settings(_env_file=None, allow_shared_ingest=False))
    with pytest.raises(HTTPException) as exc:
        ingest("S01", [], store)
    assert exc.value.status_code == 403
