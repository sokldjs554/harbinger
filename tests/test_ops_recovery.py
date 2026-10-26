"""A past resolution is insufficient when an alert has fired again."""

from scripts.check_local_operations import alert_recovery_complete


def payload(state):
    return {"data": {"groups": [{"rules": [{"name": "Slow", "state": state}]}]}}


def notice(state):
    return {"state": state, "alert": {"labels": {"alertname": "Slow"}}}


def test_refiring_after_past_resolution_is_not_recovery():
    history = [notice("firing"), notice("resolved"), notice("firing")]
    assert not alert_recovery_complete({"Slow"}, history, payload("firing"))
    assert not alert_recovery_complete({"Slow"}, history, payload("inactive"))
    history.append(notice("resolved"))
    assert not alert_recovery_complete({"Slow"}, history, payload("pending"))
    assert alert_recovery_complete({"Slow"}, history, payload("inactive"))


def test_missing_alert_state_or_receipt_does_not_count_as_recovered():
    assert not alert_recovery_complete({"Slow"}, [], payload("inactive"))
    assert not alert_recovery_complete({"Slow"}, [notice("resolved")], {"data": {"groups": []}})
