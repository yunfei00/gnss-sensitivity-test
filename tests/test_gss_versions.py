from desktop.gss_versions import DIALECTS
from desktop.core import DeviceError
import pytest

def test_v6():
    v = DIALECTS["6.00.02"]
    assert v.time_command == "-,TIME"
    assert not v.read_power
    with pytest.raises(DeviceError):
        v.power_query(23)

def test_v10():
    v = DIALECTS["10.02.00"]
    assert v.time_command == "TIME"
    assert v.read_power
    assert v.power_query(23) == "-,SIG_LEVEL,V1_A1,GPS,23,0"
    with pytest.raises(DeviceError):
        v.power_query(0)


def test_power_objects():
    assert DIALECTS["6.00.02"].power_template == "-,POW_LEV,v1_a1,{value},GPS,23,0,0,1,1,1,1"
    assert DIALECTS["10.02.00"].power_template == "-,POW_LEV,v1,{value},GPS,23,0,0,1,1,1,1"
