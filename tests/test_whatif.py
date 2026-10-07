"""What-if(반사실) — 상태를 바꾸지 않고, 같은 기록으로 바꾸면 기준선과 같고, 입력 검증이 있다."""

import pytest

from tests.conftest import first_site


def _first_asset(client, sid):
    return client.get(f"/v1/sites/{sid}/assets?limit=1").json()["assets"][0]["asset_id"]


def test_presets_isolate_the_memo(client):
    sid = first_site(client)
    aid = _first_asset(client, sid)
    pre = client.get(f"/v1/sites/{sid}/assets/{aid}/whatif/presets").json()["scenarios"]
    assert [s["id"] for s in pre] == list("ABCD")
    a, b = pre[0], pre[1]
    assert a["items"] == b["items"] and a["overall"] == b["overall"] == 0, (
        "A 와 B 는 체크리스트가 똑같아야 한다"
    )
    assert a["memo"] != b["memo"]
    assert pre[3]["overall"] == 2 and pre[2]["overall"] == 1


def test_whatif_does_not_mutate_state(client):
    sid = first_site(client)
    store = client.app.state.store
    aid = _first_asset(client, sid)
    pre = client.get(f"/v1/sites/{sid}/assets/{aid}/whatif/presets").json()["scenarios"]
    n_ins, n_x = len(store.tables["inspections"]), len(store.X)
    r = client.post(f"/v1/sites/{sid}/assets/{aid}/whatif", json={"scenarios": pre})
    assert r.status_code == 200, r.text
    j = r.json()
    base = j["baseline"]["p30"]
    assert 0 < base < 1 and len(j["scenarios"]) == 4
    for s in j["scenarios"]:
        assert 0 < s["p30"] < 1 and abs(s["delta"] - (s["p30"] - base)) < 1e-9
        assert s["memo_analysis"]["memo"] == s["memo"]
    assert len(store.tables["inspections"]) == n_ins and len(store.X) == n_x, (
        "dry-run 이 서버 상태를 바꾸면 안 된다"
    )


def test_replacing_last_inspection_with_itself_changes_nothing(client):
    """강한 성질: 마지막 점검을 실제와 똑같은 기록으로 바꾸면 위험도는 기준선과 같아야 한다 (파이프라인이 결정론적이고 누수가 없다는 뜻)."""
    sid = first_site(client)
    aid = _first_asset(client, sid)
    pre = client.get(f"/v1/sites/{sid}/assets/{aid}/whatif/presets").json()["scenarios"]
    b = client.post(f"/v1/sites/{sid}/assets/{aid}/whatif", json={"scenarios": pre[:1]}).json()["baseline"]
    same = {
        "id": "same",
        "items": b["items"],
        "overall": b["overall"],
        "memo": b["memo"],
        "dwell_seconds": b["dwell_seconds"],
        "inspector_id": b["inspector_id"],
    }
    r = client.post(f"/v1/sites/{sid}/assets/{aid}/whatif", json={"scenarios": [same]}).json()
    assert r["scenarios"][0]["p30"] == pytest.approx(b["p30"], abs=1e-9)
    assert r["scenarios"][0]["changed"] == []


def test_whatif_validation(client):
    sid = first_site(client)
    aid = _first_asset(client, sid)
    bad_item = {"scenarios": [{"items": {"not_an_item": 1}, "memo": "x"}]}
    assert client.post(f"/v1/sites/{sid}/assets/{aid}/whatif", json=bad_item).status_code == 422
    assert (
        client.post(f"/v1/sites/{sid}/assets/NOPE/whatif", json={"scenarios": [{"memo": "x"}]}).status_code
        == 404
    )
    assert client.post(f"/v1/sites/{sid}/assets/{aid}/whatif", json={"scenarios": []}).status_code == 422
    too_many = {"scenarios": [{"memo": "x"}] * 7}
    assert client.post(f"/v1/sites/{sid}/assets/{aid}/whatif", json=too_many).status_code == 422
