"""Finite FIFO waiting absorbs bursts without increasing concurrent model calls."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException


def test_waiting_request_runs_after_release_and_excess_is_rejected():
    from harbinger.api.compute import ComputeGate

    gate = ComputeGate(slots=1, waiting=1, timeout=2)
    entered = threading.Event()
    release = threading.Event()
    second = threading.Event()

    def first():
        with gate.slot():
            entered.set()
            assert release.wait(3)

    def waiting():
        with gate.slot():
            second.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first)
        assert entered.wait(2)
        b = pool.submit(waiting)
        with gate.condition:
            assert gate.condition.wait_for(lambda: len(gate.queue) == 1, timeout=2)
        try:
            with pytest.raises(HTTPException) as error, gate.slot():
                pytest.fail("capacity exceeded")
            assert error.value.status_code == 429
            assert error.value.headers["X-Harbinger-Capacity"] == "queue_full"
            assert error.value.headers["Retry-After"] == "1"
            assert not second.is_set()
        finally:
            release.set()
        a.result(timeout=3)
        b.result(timeout=3)
    assert second.is_set()
    assert gate.active == 0 and not gate.queue


def test_timeout_and_computation_exception_do_not_leak_capacity():
    from harbinger.api.compute import ComputeGate

    gate = ComputeGate(slots=1, waiting=1, timeout=0.01)
    with gate.slot():
        with pytest.raises(HTTPException) as error, gate.slot():
            pytest.fail("busy computation slot acquired")
        assert error.value.headers["X-Harbinger-Capacity"] == "wait_timeout"
        assert gate.active == 1 and not gate.queue
    with pytest.raises(RuntimeError), gate.slot():
        raise RuntimeError("model failed")
    with gate.slot():
        assert gate.active == 1
    assert gate.active == 0 and not gate.queue


def test_active_limit_and_fifo_order_are_preserved():
    from harbinger.api.compute import ComputeGate

    gate = ComputeGate(slots=1, waiting=2, timeout=2)
    order = []

    def waiter(number):
        with gate.slot():
            assert gate.active == 1
            order.append(number)

    with ThreadPoolExecutor(max_workers=2) as pool:
        with gate.slot():
            a = pool.submit(waiter, 1)
            with gate.condition:
                assert gate.condition.wait_for(lambda: len(gate.queue) == 1, timeout=2)
            b = pool.submit(waiter, 2)
            with gate.condition:
                assert gate.condition.wait_for(lambda: len(gate.queue) == 2, timeout=2)
        a.result(timeout=3)
        b.result(timeout=3)
    assert order == [1, 2]


@pytest.mark.parametrize("slots,waiting,timeout", [(0, 1, 1), (1, -1, 1), (1, 1, 0)])
def test_invalid_compute_limits_are_rejected(slots, waiting, timeout):
    from harbinger.api.compute import ComputeGate

    with pytest.raises(ValueError):
        ComputeGate(slots=slots, waiting=waiting, timeout=timeout)


def test_analysis_upload_download_and_evidence_share_gate(client, monkeypatch):
    from contextlib import contextmanager

    from harbinger.api.compute import ComputeGate
    from harbinger.api.routers import workbench

    calls = []

    class ObservedGate(ComputeGate):
        @contextmanager
        def slot(self):
            with super().slot():
                calls.append(1)
                yield

    monkeypatch.setattr(workbench, "compute", ObservedGate())
    example = client.post("/v1/workbench/example").json()
    token = example["session_id"]
    params = {"as_of": example["default_as_of"]}
    base = f"/v1/workbench/sessions/{token}"
    analysis = client.get(base + "/analysis", params=params)
    assert analysis.status_code == 200
    assert client.get(base + "/download", params=params).status_code == 200
    aid = analysis.json()["assets"][0]["asset_id"]
    assert client.get(base + f"/assets/{aid}", params=params).status_code == 200
    csv = client.get("/v1/workbench/example.csv").content
    upload = client.post(
        "/v1/workbench/upload",
        params={"observation_end": example["latest_as_of_date"]},
        content=csv,
        headers={"Content-Type": "text/csv"},
    )
    assert upload.status_code == 200
    assert len(calls) == 4
    assert workbench.compute.active == 0 and not workbench.compute.queue
    assert client.get("/v1/workbench/info").json()["compute_policy"] == {
        "slots": 2,
        "waiting": 4,
        "timeout_seconds": 10.0,
    }
    for sid in (token, upload.json()["session_id"]):
        client.delete(f"/v1/workbench/sessions/{sid}")
