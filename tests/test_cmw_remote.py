import pytest
from desktop.cmw_remote import validate, FIELDS, CmwSession
from desktop.core import DeviceError

def test_fields():
    assert validate("band","ob3")=="OB3"
    assert validate("bandwidth","B100")=="B100"
    assert validate("power","-85")=="-85.0"
    assert FIELDS["power"].endswith("RSEPre:LEVel")
    for key,value in [("power","nan"),("band","OB3;*RST"),("channel","-1"),("bandwidth","20")]:
        with pytest.raises(DeviceError):
            validate(key,value)

def test_configure_requires_off():
    session=CmwSession("unused",5025,lambda _:None)
    session.cell=lambda:"ON"
    with pytest.raises(DeviceError):
        session.configure("band","OB3")

def test_power_readback():
    session=CmwSession("unused",5025,lambda _:None)
    session.write=lambda cmd:None
    session.read=lambda cmd:"-80"
    with pytest.raises(DeviceError):
        session.configure("power","-85")
