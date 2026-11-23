import csv
import json
from threading import Event

import pytest

from desktop.adb import AdbDevice, AdbSnapshot, UsbRun
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
    report_html = html.read_text(encoding="utf-8")
    for detail in ("MOCK", "最后通过档", "运行摘要", "完整配置与设备证据", "report.csv", "report.json", "run.sqlite"):
        assert detail in report_html
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


def test_lte_drop_during_observation_invalidates_phone_timeout(ledger, monkeypatch):
    config = RunConfig(-120, 1)
    faults = Faults(["timeout"])
    simulator, lte, phone = mock_devices(config, faults)
    verify = lte.verify_lte_environment
    checks = 0

    def verify_lte():
        nonlocal checks
        checks += 1
        if checks == 2:
            faults.remaining["lte_unregistered"] = 1
        return verify()

    monkeypatch.setattr(lte, "verify_lte_environment", verify_lte)
    run_id = ledger.create_run(config)
    result = TestEngine(ledger, run_id, simulator, lte, phone).execute()
    level = snapshot(ledger, run_id)["levels"][0]
    assert result["status"] == "FINISHED"
    assert level["attempts"][0]["status"] == "INVALID"
    assert level["pass_count"] == 20


def test_field_usb_loss_preserves_completed_attempts_and_requires_new_execution(ledger, monkeypatch):
    config = RunConfig(-120, 1, scenario_id="fixture", scenario_hash="fixture",
                       calibration_ref="fixture", scenario_signals="GPS L1", mock=False)
    simulator, lte, phone = mock_devices(config)
    simulator.mock = lte.mock = phone.mock = False
    monkeypatch.setattr(simulator, "identify", lambda: {
        "model": "GSS7000", "software": "SimREPLAYplus", "version": "fixture",
        "min_power_dbm": -140, "max_power_dbm": -110,
    })
    get_state = simulator.get_state
    monkeypatch.setattr(simulator, "get_state", lambda: get_state() | {"rf_off": not simulator.running})
    status = phone.status
    monkeypatch.setattr(phone, "status", lambda: status() | {"device_id": "fixture-installation"})
    observation = phone._result

    def field_result(*args):
        observation(*args)
        phone.events[-1]["payload"]["satellite_association"] = "BRACKETED_STABLE_CALLBACKS"

    monkeypatch.setattr(phone, "_result", field_result)
    serial = AdbDevice("fixture", 1)
    usb = UsbRun(serial)
    run_id = ledger.create_run(config)
    exchange = phone.send_command

    def disconnect_after_second_start(command):
        usb.check()
        is_second = command["type"] == "START_ATTEMPT" and len(phone.started) == 1
        if is_second:
            phone.faults.remaining["hold_attempt"] = 1
        exchange(command)
        if is_second:
            usb.observe(AdbSnapshot((AdbDevice("another", 2),)))

    monkeypatch.setattr(phone, "check_connection", usb.check)
    monkeypatch.setattr(phone, "send_command", disconnect_after_second_start)
    prepare = lambda *_: "fixture preparation"
    result = TestEngine(ledger, run_id, simulator, lte, phone, prepare=prepare).execute()
    level = snapshot(ledger, run_id)["levels"][0]
    assert result["status"] == "PAUSED" and "USB 通信异常" in result["reason"]
    assert [row["status"] for row in level["attempts"]] == ["PASS", "INVALID"]
    assert len(phone.started) == 2 and simulator.running is False
    assert not any(row["operation"] == "reconnect" for row in ledger.logs(run_id))

    reconnected = AdbDevice("fixture", 3)
    usb.observe(AdbSnapshot((reconnected,)))
    assert ledger.run(run_id)["status"] == "PAUSED" and len(phone.started) == 2
    monkeypatch.setattr(phone, "check_connection", UsbRun(reconnected).check)
    monkeypatch.setattr(phone, "send_command", exchange)
    result = TestEngine(ledger, run_id, simulator, lte, phone, prepare=prepare).execute(resume=True)
    assert result["status"] == "FINISHED"
    restored = snapshot(ledger, run_id)["levels"][0]
    assert restored["pass_count"] == 20 and restored["invalid_count"] == 1
    assert restored["attempts"][:2] == level["attempts"]


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
