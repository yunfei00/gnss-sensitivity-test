import csv
import json
from threading import Event

import pytest

from desktop.core import RunConfig
from desktop.engine import TestEngine
from desktop.mock import Faults, mock_devices
from desktop.reports import export, snapshot
from desktop.storage import Store


@pytest.fixture
def ledger(tmp_path):
    with Store(tmp_path / "run.sqlite") as store:
        yield store


def run(ledger, faults=(), config=None, passing_through=-121):
    config = config or RunConfig(-122, 3)
    run_id = ledger.create_run(config)
    devices = mock_devices(config, Faults(faults), passing_through)
    result = TestEngine(ledger, run_id, *devices).execute()
    assert not devices[0].running or result["status"] == "PAUSED"
    assert devices[2].active is None
    return result, snapshot(ledger, run_id)


def test_mock_report_and_power_sweep(ledger):
    result, report = run(ledger)
    assert [level["power_dbm"] for level in report["levels"]] == [-120, -121, -122]
    assert [level["pass_count"] for level in report["levels"]] == [20, 20, 0]
    assert [level["valid_count"] for level in report["levels"]] == [20, 20, 20]
    assert result["threshold_dbm"] == -121
    assert result["reason"] == "LEVEL_FAILED"
    html = export(ledger, result["id"])
    assert "MOCK" in html.read_text(encoding="utf-8")
    data = json.loads(html.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["run"]["evidence"]["lte"]["registered"] is True
    assert data["events"] and data["device_logs"]
    with html.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 60
    assert rows[0]["ttff_s"] == "8.0"


@pytest.mark.parametrize("failed,passes,outcome,threshold", [
    (1, 19, "MIN_POWER_REACHED", -120), (2, 18, "NOT_PASSED_AT_START", None),
])
def test_level_boundary(ledger, failed, passes, outcome, threshold):
    result, report = run(ledger, ["timeout"] * failed, RunConfig(-120, 1))
    assert result["reason"] == outcome
    assert result["threshold_dbm"] == threshold
    assert report["levels"][0]["valid_count"] == 20
    assert report["levels"][0]["pass_count"] == passes


def test_max_levels_limit(ledger):
    result, report = run(ledger, config=RunConfig(-140, 1))
    assert result["reason"] == "MAX_LEVELS_REACHED"
    assert len(report["levels"]) == 1


@pytest.mark.parametrize("fault", ["no_satellite", "phone_health", "phone_prepare", "disconnect", "drop_ack"])
def test_invalid_retry_and_replay(ledger, fault):
    result, report = run(ledger, [fault], RunConfig(-120, 1))
    assert result["status"] == "FINISHED"
    level = report["levels"][0]
    assert (level["valid_count"], level["pass_count"], level["invalid_count"]) == (20, 20, 1)
    phone_events = [e for e in report["events"] if e["source"] == "phone"]
    ids = {event["message_id"] for event in phone_events}
    assert len(ids) == len(phone_events)
    if fault in {"disconnect", "drop_ack"}:
        first = level["attempts"][0]["id"]
        assert any(e["attempt_id"] == first and e["event_type"] == "ATTEMPT_RESULT" for e in phone_events)
        assert any(log["operation"] == "reconnect" for log in report["device_logs"])


@pytest.mark.parametrize("fault", ["gss_connect", "gss_set_power", "gss_readback", "lte_unregistered", "phone_connect"])
def test_unhealthy_device_never_counts_as_gnss_failure(ledger, fault):
    result, report = run(ledger, [fault])
    assert result["status"] == "PAUSED"
    assert result["threshold_dbm"] is None
    assert not any(level["valid_count"] for level in report["levels"])


def test_retry_budget(ledger):
    result, report = run(ledger, ["no_satellite"] * 4)
    assert result["status"] == "PAUSED"
    assert report["invalid_count"] == 3
    assert report["levels"][0]["valid_count"] == 0


def test_safe_stop_failure_prevents_finished(ledger):
    result, _ = run(ledger, ["gss_stop"], RunConfig(-120, 1))
    assert result["status"] == "PAUSED"
    assert "RF" in result["reason"]


def test_user_stop_and_resume_preserves_counts(ledger):
    config = RunConfig(-120, 1)
    run_id = ledger.create_run(config)
    stop = Event()
    recorded = []

    def notify(kind, data):
        if kind == "ATTEMPT":
            recorded.append(data["attempt_id"])
        if kind == "STATE" and data["state"] == "ATTEMPT_RUNNING" and recorded:
            stop.set()

    simulator, lte, phone = mock_devices(config)
    result = TestEngine(ledger, run_id, simulator, lte, phone, stop, notify).execute()
    assert result["status"] == "STOPPED"
    assert len(phone.started) == 1
    assert not simulator.running
    assert phone.active is None
    initial = snapshot(ledger, run_id)["levels"][0]["attempts"]
    assert [row["status"] for row in initial] == ["PASS", "INVALID"]

    resumed = TestEngine(ledger, run_id, simulator, lte, phone).execute(resume=True)
    level = snapshot(ledger, run_id)["levels"][0]
    assert resumed["status"] == "FINISHED"
    assert level["pass_count"] == 20
    assert level["attempts"][:2] == initial


def test_recover_after_host_interruption(ledger):
    config = RunConfig(-120, 1)
    run_id = ledger.create_run(config)
    simulator, lte, phone = mock_devices(config)
    simulator.start()
    simulator.set_power(-120)
    level = ledger.level(run_id, -120)
    attempt = ledger.create_attempt(level["id"])
    ledger.state(run_id, "ATTEMPT_RUNNING")
    phone.active_run, phone.active = run_id, attempt
    result = TestEngine(ledger, run_id, simulator, lte, phone).execute(resume=True)
    assert result["status"] == "FINISHED"
    details = snapshot(ledger, run_id)["levels"][0]
    assert details["invalid_count"] == 1
    assert details["pass_count"] == 20
    assert details["attempts"][0]["reason"] == "HOST_INTERRUPTED"


def test_resume_power_mismatch_is_paused(ledger):
    config = RunConfig(-120, 1)
    run_id = ledger.create_run(config)
    ledger.level(run_id, -120)
    ledger.state(run_id, "ATTEMPT_RUNNING")
    simulator, lte, phone = mock_devices(config)
    simulator.start()
    simulator.set_power(-121)
    result = TestEngine(ledger, run_id, simulator, lte, phone).execute(resume=True)
    assert result["status"] == "PAUSED"
    assert not phone.started
    assert not simulator.running
