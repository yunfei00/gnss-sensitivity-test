"""P5 stepped sensitivity scan using the P4 validated fixed-power contract.

One shared calibration reference, a fresh 20-valid-attempt batch per level,
and no fabricated measurement or readback. Each P4 batch performs its own
preflight and safe shutdown; failures halt the sweep.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import json
from .core import START_DBM, DeviceError
from .stage4_fixed import FixedPowerPlan, run_fixed_power, _persist


@dataclass(frozen=True)
class SweepPlan:
    minimum_dbm: int
    maximum_levels: int
    reference_lat: float
    reference_lon: float
    scenario_id: str
    calibration_ref: str
    startup_mode: str = "HOT"
    observation_s: float = 30.0

    def __post_init__(self):
        if type(self.minimum_dbm) is not int or self.minimum_dbm > START_DBM:
            raise ValueError("最低功率必须是 <= -120 dBm 的整数")
        if type(self.maximum_levels) is not int or not 1 <= self.maximum_levels <= 200:
            raise ValueError("档数必须在 1 到 200 之间")
        FixedPowerPlan(float(START_DBM), self.reference_lat, self.reference_lon,
                       self.scenario_id, self.calibration_ref, self.startup_mode,
                       self.observation_s)


def run_sensitivity_sweep(plan, cmw, gss, phone, directory, stop=None, notify=None):
    """Factory objects may be callables returning a new adapter per level.

    Each level creates a separate immutable JSON file. Existing output is never
    overwritten. This also permits post-crash inspection of all prior levels.
    """
    stop = stop if stop is not None else Event()
    notify = notify or (lambda *_: None)
    directory = Path(directory)
    summary_path = directory / "sweep.json"
    if summary_path.exists() or directory.exists() and any(directory.iterdir()):
        raise FileExistsError("测试目录非空，禁止覆盖或混用历史数据")
    directory.mkdir(parents=True, exist_ok=True)
    summary = {"phase": "P5", "mode": "REAL_HARDWARE", "status": "RUNNING",
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "plan": vars(plan).copy(), "levels": [], "threshold_dbm": None}
    _persist(summary_path, summary)
    try:
        for index in range(plan.maximum_levels):
            power = START_DBM - index
            if power < plan.minimum_dbm:
                break
            if stop.is_set():
                summary["status"] = "STOPPED"
                summary["reason"] = "USER_STOP"
                break
            notify("LEVEL_START", {"power_dbm": power, "index": index})
            level = FixedPowerPlan(float(power), plan.reference_lat, plan.reference_lon,
                                   plan.scenario_id, plan.calibration_ref,
                                   plan.startup_mode, plan.observation_s)
            devices = tuple(device() if callable(device) else device for device in (cmw, gss, phone))
            result = run_fixed_power(level, *devices, directory / f"level_{power}.json",
                                     stop=stop, notify=notify)
            summary["levels"].append({"power_dbm": power, "status": result["status"],
                                      "verdict": result.get("verdict"),
                                      "valid": result["valid"], "passed": result["passed"],
                                      "file": f"level_{power}.json"})
            _persist(summary_path, summary)
            notify("LEVEL_DONE", summary["levels"][-1])
            if result["status"] != "FINISHED":
                summary["status"] = result["status"]
                summary["reason"] = result.get("reason", "DEVICE_ERROR")
                break
            if result["verdict"] == "FAIL":
                summary["status"] = "FINISHED"
                summary["reason"] = "NOT_PASSED_AT_START" if index == 0 else "LEVEL_FAILED"
                break
            summary["threshold_dbm"] = power
        else:
            summary["status"] = "FINISHED"
            summary["reason"] = "MAX_LEVELS_REACHED"
        if summary["status"] == "RUNNING":
            summary["status"] = "FINISHED"
            summary["reason"] = "MIN_POWER_REACHED"
    except Exception as exc:
        summary["status"] = "PAUSED"
        summary["reason"] = str(exc)
    finally:
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        _persist(summary_path, summary)
        notify("SWEEP_DONE", summary)
    return summary
