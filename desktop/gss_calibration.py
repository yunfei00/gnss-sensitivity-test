"""Explicit, site-verified conversion of RF output dBm to SimREPLAYplus POW_LEV dB.

This is not a factory calibration or a power measurement. A calibration
certificate and a measured reference point are mandatory inputs.
"""
from dataclasses import dataclass
from math import isfinite
from .core import DeviceError
from .gss_versions import DIALECTS


@dataclass(frozen=True)
class GssCalibration:
    version: str
    measured_output_dbm: float
    command_reference_db: float
    evidence: str
    output_plane: str
    valid_min_dbm: float
    valid_max_dbm: float

    def __post_init__(self):
        if self.version not in DIALECTS:
            raise DeviceError("未支持的 SimREPLAYplus 版本")
        values = (self.measured_output_dbm, self.command_reference_db,
                  self.valid_min_dbm, self.valid_max_dbm)
        if not all(type(v) in (float, int) and isfinite(v) for v in values):
            raise DeviceError("校准值必须是有限数值")
        if not self.valid_min_dbm <= self.measured_output_dbm <= self.valid_max_dbm:
            raise DeviceError("校准参考点超出已核验范围")
        if not self.evidence.strip() or not self.output_plane.strip():
            raise DeviceError("必须记录校准证据和输出参考平面")

    def to_reference_db(self, target_dbm):
        if not isfinite(target_dbm) or not self.valid_min_dbm <= target_dbm <= self.valid_max_dbm:
            raise DeviceError("目标 dBm 超出已校准范围，禁止发送")
        return round(self.command_reference_db + target_dbm - self.measured_output_dbm, 4)

    def command(self, target_dbm):
        reference = self.to_reference_db(target_dbm)
        return DIALECTS[self.version].power_template.replace("{value}", f"{reference:g}")
