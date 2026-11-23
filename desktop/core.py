"""Run configuration and GNSS verdicts. The phone supplies raw monotonic timestamps."""
from dataclasses import dataclass
from math import isfinite

from geographiclib.geodesic import Geodesic

START_DBM = -120
SAMPLES = 20
PASS_COUNT = 19
TTFF_S = 20.3
ERROR_M = 101.3
SATELLITES = 4
INVALID_RETRIES = 2


class DeviceError(Exception):
    """Instrument, phone or telemetry path cannot support a GNSS verdict."""


class LinkError(DeviceError):
    """Transport response is missing or untrustworthy."""


class UserStop(Exception):
    """The operator cancelled the run."""


@dataclass(frozen=True)
class RunConfig:
    min_power_dbm: int
    max_levels: int
    scenario_id: str = "synthetic-static"
    scenario_hash: str = "synthetic-v1"
    reference_lat: float = 0.0
    reference_lon: float = 0.0
    startup_mode: str = "HOT"
    observation_s: float = 30.0
    satellite_tolerance_ms: int = 1000
    settle_s: float = 0.0
    power_tolerance_db: float = 0.1
    calibration_ref: str = "synthetic"
    power_definition: str = "simulator setting"
    scenario_signals: str = "synthetic GNSS"
    mock: bool = True

    def __post_init__(self):
        if type(self.min_power_dbm) is not int or self.min_power_dbm > START_DBM:
            raise ValueError("最低功率须为不高于 -120 dBm 的整数")
        if type(self.max_levels) is not int or not 1 <= self.max_levels <= 200:
            raise ValueError("最大档数须在 1–200 之间")
        if self.startup_mode not in {"HOT", "WARM", "COLD", "AGPS"}:
            raise ValueError("启动模式无效")
        if not (-90 <= self.reference_lat <= 90 and -180 <= self.reference_lon <= 180):
            raise ValueError("WGS84 坐标超出范围")
        if not TTFF_S <= self.observation_s <= 300 or not 0 <= self.settle_s <= 300:
            raise ValueError("观察窗口或功率稳定等待时间无效")
        if type(self.satellite_tolerance_ms) is not int or not 1 <= self.satellite_tolerance_ms <= 2000:
            raise ValueError("卫星关联时间窗口须在 1–2000 ms 之间")
        if not 0 <= self.power_tolerance_db < 0.5:
            raise ValueError("功率读回容差须小于 0.5 dB")
        for field in (self.scenario_id, self.scenario_hash, self.calibration_ref,
                      self.power_definition, self.scenario_signals):
            if not isinstance(field, str) or not field.strip():
                raise ValueError("场景、哈希、校准引用、信号和功率定义均为必填项")
        if type(self.mock) is not bool:
            raise ValueError("测试模式必须明确")
        if not self.mock and ("synthetic" in self.scenario_id.lower()
                              or "synthetic" in self.scenario_hash.lower()
                              or "synthetic" in self.calibration_ref.lower()
                              or "synthetic" in self.scenario_signals.lower()):
            raise ValueError("真机运行须提供现场场景、哈希、信号和校准引用")

    @property
    def reference(self):
        return {"latitude": self.reference_lat, "longitude": self.reference_lon}


def evaluate(config: RunConfig, payload: dict) -> dict:
    fields = ("t0_monotonic_ns", "first_fix_elapsed_realtime_ns", "latitude",
              "longitude", "used_in_fix", "satellite_elapsed_ns", "satellite_association")
    result = {key: payload[key] for key in fields if key in payload}

    def verdict(status, reason):
        return {**result, "status": status, "reason": reason}

    if payload.get("integrity") != "COMPLETE":
        return verdict("INVALID", str(payload.get("reason") or "INVALID_TELEMETRY"))
    t0 = payload.get("t0_monotonic_ns")
    if type(t0) is not int or t0 < 0:
        return verdict("INVALID", "INVALID_START_TIME")
    if payload.get("reason") == "TIMEOUT" and payload.get("status") == "FAIL":
        if payload.get("first_fix_elapsed_realtime_ns") is None:
            return verdict("FAIL", "TIMEOUT")
        return verdict("INVALID", "INCONSISTENT_TIMEOUT")
    if (payload.get("status") != "OBSERVED" or payload.get("source") != "GPS_PROVIDER"
            or payload.get("mock_location", False)):
        return verdict("INVALID", "INVALID_FIX_SOURCE")
    fix = payload.get("first_fix_elapsed_realtime_ns")
    if type(fix) is not int or not 0 < fix - t0 <= round(config.observation_s * 1e9):
        return verdict("INVALID", "INVALID_FIX_TIME")
    lat, lon = payload.get("latitude"), payload.get("longitude")
    if (type(lat) not in (float, int) or type(lon) not in (float, int)
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)):
        return verdict("INVALID", "INVALID_COORDINATES")
    result["ttff_s"] = (fix - t0) / 1e9
    result["horizontal_error_m"] = Geodesic.WGS84.Inverse(
        config.reference_lat, config.reference_lon, lat, lon
    )["s12"]
    used, satellite = payload.get("used_in_fix"), payload.get("satellite_elapsed_ns")
    expected = "MOCK" if config.mock else "BRACKETED_STABLE_CALLBACKS"
    if (type(used) is not int or used < 0 or payload.get("satellite_association") != expected
            or type(satellite) is not int or satellite < t0
            or abs(satellite - fix) > config.satellite_tolerance_ms * 1_000_000):
        return verdict("INVALID", "UNRELIABLE_USED_IN_FIX")

    failed = []
    if fix - t0 > round(TTFF_S * 1e9):
        failed.append("TTFF")
    # The inverse geodesic at a constructed boundary can differ by numerical round-off.
    if result["horizontal_error_m"] > ERROR_M + 1e-8:
        failed.append("HORIZONTAL_ERROR")
    if used < SATELLITES:
        failed.append("USED_IN_FIX")
    return verdict("FAIL", "+".join(failed)) if failed else verdict("PASS", "THRESHOLDS_MET")


def verified_readback(value, power, tolerance):
    if type(value) not in (int, float) or not isfinite(value) or abs(value - power) > tolerance + 1e-9:
        raise DeviceError(f"功率读回不匹配 ({value!r}, 预期 {power} dBm)")
    return value
