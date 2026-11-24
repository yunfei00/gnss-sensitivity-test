"""P4 fixed-power 20-attempt orchestration. No synthetic verdicts or power scan.

Hardware adapters are injected; no RF command is issued until preflight succeeds.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import json
import math
from uuid import uuid4

from .core import DeviceError, UserStop, evaluate, SAMPLES, PASS_COUNT


@dataclass(frozen=True)
class FixedPowerPlan:
    power_dbm: float
    reference_lat: float
    reference_lon: float
    scenario_id: str
    calibration_ref: str
    startup_mode: str = "HOT"
    observation_s: float = 30.0
    max_invalid_retries: int = 2

    def __post_init__(self):
        if not math.isfinite(self.power_dbm) or not -200 <= self.power_dbm <= 50:
            raise ValueError("固定功率无效")
        if not -90 <= self.reference_lat <= 90 or not -180 <= self.reference_lon <= 180:
            raise ValueError("参考坐标无效")
        if not self.scenario_id.strip() or not self.calibration_ref.strip():
            raise ValueError("必须提供真实场景和校准依据")
        if self.startup_mode not in ("HOT", "WARM", "COLD", "AGPS"):
            raise ValueError("启动模式无效")
        if not 20.3 <= self.observation_s <= 300:
            raise ValueError("观察时间无效")
        if not 0 <= self.max_invalid_retries <= 10:
            raise ValueError("无效重试次数无效")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _persist(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def run_fixed_power(plan, cmw, gss, phone, output, stop=None, notify=None):
    """Run against verified adapters.

    cmw: optional; None means GNSS_ONLY and skips all LTE operations.\n         Otherwise preflight(), establish_lte(), rrc_connected(), safe_stop()
    gss: preflight(), start_scenario(scenario_id), set_power_dbm(dbm),
         verify_power_dbm(dbm), safe_stop()
    phone: preflight(), prepare(mode), attempt(reference, observation_s),
           stop_run(). attempt returns *raw* Android telemetry payload for
           core.evaluate; it must not supply a precomputed PASS verdict.
    """
    stop = stop or Event()
    notify = notify or (lambda event, data: None)
    output = Path(output)
    if output.exists():
        raise FileExistsError("拒绝覆盖已有测试结果")
    run_id = str(uuid4())
    record = {"run_id": run_id, "phase": "P4", "mode": "REAL_HARDWARE",
              "started_utc": _now(), "plan": vars(plan).copy(),
              "status": "RUNNING", "test_mode": "GNSS_ONLY" if cmw is None else "GNSS_LTE",\n              "attempts": [], "valid": 0, "passed": 0}
    _persist(output, record)
    touched = []
    try:
        for name, device in (("CMW500", cmw), ("GSS7000", gss), ("USB", phone)):
            if device is None:
                continue
            if stop.is_set():
                raise UserStop("USER_STOP")
            if name == "USB":
                touched.append(("phone", phone))  # USB preflight may already own a live session.
            device.preflight()
            notify("PREFLIGHT", {"device": name})
        if cmw is not None:
            touched.append(("cmw", cmw))
            cmw.establish_lte()
            if not cmw.rrc_connected():
                raise DeviceError("LTE RRC 未连接")
        touched.append(("gss", gss))
        gss.start_scenario(plan.scenario_id)
        gss.set_power_dbm(plan.power_dbm)
        if gss.verify_power_dbm(plan.power_dbm) is not True:
            raise DeviceError("GNSS 固定功率未核验；禁止生成正式结果")
        # evaluate expects the same real-data contract as the existing engine.
        from .core import RunConfig
        config = RunConfig(min_power_dbm=-200, max_levels=1,
                           scenario_id=plan.scenario_id, scenario_hash="field-verified",
                           calibration_ref=plan.calibration_ref,
                           reference_lat=plan.reference_lat,
                           reference_lon=plan.reference_lon,
                           startup_mode=plan.startup_mode, observation_s=plan.observation_s,
                           power_definition="calibrated RF output dBm",
                           scenario_signals="field GNSS", mock=False)
        invalid = 0
        while record["valid"] < SAMPLES:
            if stop.is_set():
                raise UserStop("USER_STOP")
            if cmw is not None and not cmw.rrc_connected():
                raise DeviceError("LTE RRC 连接丢失")
            if gss.verify_power_dbm(plan.power_dbm) is not True:
                raise DeviceError("本轮开始前 GNSS 功率未核验")
            phone.prepare(plan.startup_mode)
            payload = phone.attempt(config.reference, plan.observation_s)
            if not isinstance(payload, dict):
                raise DeviceError("手机未返回有效原始遥测")
            if stop.is_set():
                raise UserStop("USER_STOP")
            if (cmw is not None and not cmw.rrc_connected()) or gss.verify_power_dbm(plan.power_dbm) is not True:
                raise DeviceError("采集后 LTE（若启用）或 GNSS 功率状态变化，不能计入有效试验")
            verdict = evaluate(config, payload)
            item = {"number": len(record["attempts"]) + 1, "utc": _now(), **verdict}
            record["attempts"].append(item)
            if verdict["status"] == "INVALID":
                invalid += 1
                if invalid > plan.max_invalid_retries:
                    raise DeviceError("INVALID 超过允许重试次数")
            else:
                invalid = 0
                record["valid"] += 1
                record["passed"] += int(verdict["status"] == "PASS")
            _persist(output, record)
            notify("ATTEMPT", item)
        record["success_rate"] = record["passed"] / SAMPLES
        record["status"] = "FINISHED"
        record["verdict"] = "PASS" if record["passed"] >= PASS_COUNT else "FAIL"
    except (Exception, UserStop) as exc:
        record["status"] = "STOPPED" if isinstance(exc, UserStop) else "PAUSED"
        record["reason"] = str(exc)
    finally:
        issues = []
        for name, device in reversed(touched):
            try:
                confirmed = device.stop_run() if name == "phone" else device.safe_stop()
                if confirmed is not True:
                    raise DeviceError("安全停止未确认")
            except Exception as exc:
                issues.append(name + ": " + str(exc))
        if issues:
            record["status"] = "PAUSED"
            record.pop("verdict", None)
            record["shutdown_issues"] = issues
        if record["status"] != "FINISHED":
            record.pop("verdict", None)
        record["finished_utc"] = _now()
        _persist(output, record)
        notify("DONE", record)
    return record
