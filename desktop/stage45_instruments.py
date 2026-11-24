"""Real instrument adapters for P4/P5, with explicit safety and calibration gates.

The GSS power verification callback MUST check independent RF measurement
evidence. Remote XML status alone cannot prove absolute output power.
"""
from .core import DeviceError
from .cmw_remote import CmwSession
from .gss_remote import run_operation
from .gss_calibration import GssCalibration


class CmwLteAdapter:
    def __init__(self, host, port=5025, log=None):
        self.host, self.port = host, port
        self.log = log or (lambda *_: None)
        self.owned = False

    def _call(self, method, *args):
        with CmwSession(self.host, self.port, self.log) as session:
            session.check()
            return getattr(session, method)(*args)

    def preflight(self):
        identity = self._call("read", "*IDN?")
        if "CMW" not in identity.upper():
            raise DeviceError("连接的仪表不是已核对的 CMW500: " + identity)
        self.log("CMW500 身份: " + identity)

    def establish_lte(self):
        state = self._call("cell")
        if state == "OFF":
            self.owned = True  # Set before RF-changing command for cleanup.
            self._call("switch", "ON")
        elif state != "ON":
            raise DeviceError("CMW500 小区状态未知: " + state)
        if not self.rrc_connected():
            raise DeviceError("CMW500 RRC 未连接；需另外核对 NAS 注册")

    def rrc_connected(self):
        return self._call("rrc") == "CONN"

    def safe_stop(self):
        if self.owned:
            result = self._call("switch", "OFF")
            self.owned = False
            return result == "OFF"
        return True


class GssCalibratedAdapter:
    def __init__(self, host, calibration: GssCalibration, port=15650,
                 tx_end=b"\n", confirm_power=None, log=None):
        self.host, self.port, self.tx_end = host, port, tx_end
        self.calibration = calibration
        self.confirm_power = confirm_power
        self.log = log or (lambda *_: None)
        self.owned = False
        self.power = None
        self.confirmed = False

    def _run(self, commands, expected=None):
        return run_operation(self.host, self.port, self.tx_end, commands,
                             expected, self.log)

    def preflight(self):
        state, _ = self._run(["NULL"])
        if state not in (2, 5, 7):
            raise DeviceError("GSS7000 尚未加载就绪场景")

    def start_scenario(self, scenario_id):
        if not scenario_id or any(c in scenario_id for c in '\r\n"'):
            raise DeviceError("场景路径无效")
        # Stop a previous run and load the exact scenario supplied by operator.
        self.owned = True
        self._run(["-,EN,1"], 2)
        self._run(['SC,"' + scenario_id + '"'], 2)
        self._run(["TR,0", "RU"], 5)

    def set_power_dbm(self, target):
        command = self.calibration.command(target)
        self.confirmed = False
        self.power = None
        state, _ = self._run([command])
        if state != 5:
            raise DeviceError("GSS7000 未处于运行状态")
        self.power = target
        self.log("设定目标: " + str(target) + " dBm；远程参考 dB 指令: " + command)

    def verify_power_dbm(self, target):
        state, _ = self._run(["NULL"])
        if state != 5 or self.power != target:
            self.confirmed = False
            return False
        if not self.confirmed:
            if self.confirm_power is None:
                raise DeviceError("缺少独立 RF 功率核验证据；不能把 V6 设定值视为读回")
            evidence = self.confirm_power(target, self.calibration)
            if not isinstance(evidence, str) or not evidence.strip():
                raise DeviceError("外部 RF 功率核验证据为空")
            self.log("独立功率核验: " + evidence)
            self.confirmed = True
        return True

    def safe_stop(self):
        if not self.owned:
            return True
        state, _ = self._run(["-,EN,1"], 2)
        self.owned = False
        self.power = None
        self.confirmed = False
        return state == 2
