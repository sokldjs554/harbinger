"""과거 시점 재현(백테스트) — 결과 판정이 작업지시서(WO)와 정확히 맞는지, 합산이 맞는지."""

import pandas as pd

from tests.conftest import first_site


def _week_asof(w) -> pd.Timestamp:
    return pd.Timestamp(w["as_of"]) + pd.Timedelta(hours=23, minutes=59)


def test_replay_outcomes_match_workorders(client, trained):
    sid = first_site(client)
    r = client.get(f"/v1/replay?site={sid}&k=5").json()
    assert r["weeks"], "테스트 기간에 재현할 주가 있어야 한다"
    wo = trained["tables"]["workorders"]
    bd = wo[wo["type"] == "breakdown"]
    for w in r["weeks"][:4]:
        as_of = _week_asof(w)
        assert w["held_out"] is True
        for who in ("harbinger", "round_robin"):
            hits = 0
            for it in w[who]["items"]:
                ev = bd[
                    (bd["asset_id"] == it["asset_id"])
                    & (bd["opened_at"] > as_of)
                    & (bd["opened_at"] <= as_of + pd.Timedelta(days=30))
                ]
                assert it["failed_within_30d"] == (len(ev) > 0)
                if len(ev):
                    first = (ev["opened_at"].min() - as_of).total_seconds() / 86400
                    assert abs(it["days_to_failure"] - first) < 0.11
                hits += int(len(ev) > 0)
            assert w[who]["hits"] == hits and w[who]["n"] == len(w[who]["items"])
    s = r["summary"]
    assert s["harbinger_hits"] == sum(w["harbinger"]["hits"] for w in r["weeks"])
    assert s["harbinger_picks"] == sum(w["harbinger"]["n"] for w in r["weeks"])
    assert 0 <= s["base_rate"] <= 1 and s["weeks"] == len(r["weeks"])


def test_replay_all_equals_sum_of_sites(client):
    sites = [s["site_id"] for s in client.get("/v1/sites").json()["sites"]]
    allr = client.get("/v1/replay?site=all&k=5").json()
    per = [client.get(f"/v1/replay?site={s}&k=5").json() for s in sites]
    assert allr["summary"]["harbinger_hits"] == sum(p["summary"]["harbinger_hits"] for p in per)
    assert allr["summary"]["round_robin_picks"] == sum(p["summary"]["round_robin_picks"] for p in per)
    assert allr["n_sites"] == len(sites)
    assert "items" not in allr["weeks"][0]["harbinger"], "전체 합산에는 설비 목록을 싣지 않는다"


def test_replay_uses_only_data_before_as_of(client, trained):
    """같은 주를 다른 기준 시각으로 불러도 점수 입력이 as_of 이전이라는 것 — 점검 시각이 as_of 보다 늦은 설비는 목록에 없다."""
    sid = first_site(client)
    r = client.get(f"/v1/replay?site={sid}&k=5").json()
    ins = trained["tables"]["inspections"]
    w = r["weeks"][2]
    as_of = _week_asof(w)
    last_seen = (
        ins[(ins["site_id"] == sid) & (ins["performed_at"] <= as_of)]
        .groupby("asset_id")["performed_at"]
        .max()
    )
    for it in w["harbinger"]["items"] + w["round_robin"]["items"]:
        assert it["asset_id"] in last_seen.index, "as_of 이전에 점검 기록이 있는 설비만 뽑혀야 한다"
        age = (as_of - last_seen[it["asset_id"]]).total_seconds() / 86400
        assert abs(it["days_since_inspection"] - age) < 0.01


def test_replay_validation(client):
    assert client.get("/v1/replay?site=NOPE").status_code == 404
    assert client.get("/v1/replay?site=all&from=not-a-date").status_code == 422
    early = client.get("/v1/replay?site=all&k=5&from=2024-01-01&to=2024-03-01").json()
    assert all(w["held_out"] is False for w in early["weeks"]), "학습 기간의 주는 held_out=False 로 표시된다"
