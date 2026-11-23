"""Instrument contracts. Operator confirmations are audited as manual evidence."""
from abc import ABC, abstractmethod
from time import monotonic

from .core import DeviceError
from .protocol import utc


class SimulatorAdapter(ABC):
    mock = False

    @abstractmethod
    def connect(self): ...

    @abstractmethod
    def identify(self): ...

    @abstractmethod
    def verify_scenario(self, config): ...

    @abstractmethod
    def start(self): ...

    @abstractmethod
    def set_power(self, power_dbm): ...

    @abstractmethod
    def get_state(self): ...

    @abstractmethod
    def read_power(self): ...

    @abstractmethod
    def safe_stop(self): ...


class CellularAdapter(ABC):
    mock = False

    @abstractmethod
    def connect(self): ...

    @abstractmethod
    def verify_lte_environment(self): ...

    @abstractmethod
    def capture_evidence(self): ...


class SimReplayPlusManual(SimulatorAdapter):
    """Operator reads SimREPLAYplus controls and attaches local evidence."""

    def __init__(self, confirm):
        self.confirm = confirm

    def connect(self):
        return {"control": "MANUAL", "family": "SimREPLAYplus"}

    def identify(self):
        return self.confirm("核对 GSS7000 与 SimREPLAYplus 软件版本",
                            {"model": "GSS7000", "software": "SimREPLAYplus", "version": "",
                             "min_power_dbm": None, "max_power_dbm": None, "evidence": ""})

    def verify_scenario(self, config):
        return self.confirm("核对静态场景、信号、参考坐标与校准。录入实际读值并引用证据。",
                            {"scenario_id": "", "scenario_hash": "", "reference": {},
                             "static": False, "signals": "", "calibration_ref": "",
                             "power_definition": "", "evidence": ""})

    def start(self):
        return self.confirm("在 SimREPLAYplus 启动已核对的场景并确认 RF 屏蔽",
                            {"running": False, "evidence": ""})

    def set_power(self, power_dbm):
        return self.confirm(f"在 SimREPLAYplus 设置 {power_dbm} dBm。确认单位、参考平面和实际读值。",
                            {"set_power_dbm": None, "evidence": ""})

    def get_state(self):
        return self.confirm("读取 SimREPLAYplus 当前运行状态、场景哈希和功率",
                            {"running": None, "scenario_hash": "", "power_dbm": None,
                             "rf_off": None, "evidence": ""})

    def read_power(self):
        return self.confirm("读取当前 SimREPLAYplus 功率读回值",
                            {"readback_dbm": None, "evidence": ""})

    def safe_stop(self):
        return self.confirm("在 SimREPLAYplus 停止场景并确认 GNSS RF 已关闭",
                            {"running": True, "rf_off": False, "evidence": ""}, safety=True)


class Cmw500Manual(CellularAdapter):
    def __init__(self, confirm):
        self.confirm = confirm
        self.evidence = None

    def connect(self):
        return {"model": "CMW500", "control": "MANUAL", "role": "LTE environment"}

    def verify_lte_environment(self):
        self.evidence = self.confirm(
            "在 CMW500 核对预期主频 LTE 小区与本次 DUT 的真实注册。试验后核对整个观察窗口的注册日志。",
            {"registered": False, "model": "CMW500", "firmware": "", "options": "",
             "cell": "", "band": "", "dut": "", "evidence": ""}
        )
        if not all(isinstance(self.evidence.get(key), str) and self.evidence[key].strip()
                   for key in ("model", "firmware", "options", "cell", "band", "dut", "evidence")):
            raise DeviceError("CMW500 LTE 证据字段不完整")
        return self.evidence

    def capture_evidence(self):
        return self.evidence


def audited(store, run_id, device, operation, call, *args):
    started = monotonic()
    try:
        response = call(*args)
    except Exception as exc:
        store.device_log(run_id, device, operation, args, str(exc), monotonic() - started, "ERROR", utc())
        raise
    store.device_log(run_id, device, operation, args, response, monotonic() - started, "OK", utc())
    return response
