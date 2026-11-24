"""Explicit SimREPLAYplus dialects; never infer software version from hardware ID."""
from dataclasses import dataclass
from .core import DeviceError

@dataclass(frozen=True)
class Dialect:
    version: str
    time_command: str
    read_power: bool

    def power_query(self, svid):
        if not self.read_power:
            raise DeviceError("该版本不支持远程功率读回")
        if not 1 <= svid <= 32:
            raise DeviceError("GPS SVID 必须为 1–32")
        return f"-,SIG_LEVEL,V1_A1,GPS,{svid},0"

DIALECTS = {
    "6.00.02": Dialect("6.00.02", "-,TIME", False),
    "10.02.00": Dialect("10.02.00", "TIME", True),
}
