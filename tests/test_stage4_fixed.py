from desktop.stage4_fixed import FixedPowerPlan, run_fixed_power


class Cmw:
    def preflight(self): pass
    def establish_lte(self): pass
    def rrc_connected(self): return True
    def safe_stop(self): return True


class Gss:
    def preflight(self): pass
    def start_scenario(self, scenario): assert scenario == "real-scenario"
    def set_power_dbm(self, value): assert value == -120
    def verify_power_dbm(self, value): return True
    def safe_stop(self): return True


class Phone:
    def __init__(self): self.calls = 0
    def preflight(self): pass
    def prepare(self, mode): assert mode == "HOT"
    def attempt(self, reference, observation_s):
        self.calls += 1
        t0 = self.calls * 100000000000
        return dict(integrity="COMPLETE", status="OBSERVED", source="GPS_PROVIDER",
                    t0_monotonic_ns=t0, first_fix_elapsed_realtime_ns=t0+1000000000,
                    latitude=0.0, longitude=0.0, used_in_fix=6,
                    satellite_elapsed_ns=t0+1000000000,
                    satellite_association="BRACKETED_STABLE_CALLBACKS")
    def stop_run(self): return True


def plan():
    return FixedPowerPlan(-120, 0, 0, "real-scenario", "calibration-2026")


def test_twenty_independent_attempts(tmp_path):
    phone = Phone()
    result = run_fixed_power(plan(), Cmw(), Gss(), phone, tmp_path/"run.json")
    assert result["status"] == "FINISHED"
    assert result["verdict"] == "PASS"
    assert result["valid"] == 20 and result["passed"] == 20
    assert phone.calls == 20


def test_refuse_unverified_power(tmp_path):
    class Unverified(Gss):
        def verify_power_dbm(self, value): return False
    phone = Phone()
    result = run_fixed_power(plan(), Cmw(), Unverified(), phone, tmp_path/"run.json")
    assert result["status"] == "PAUSED"
    assert result["valid"] == 0
    assert phone.calls == 0
    assert "verdict" not in result


def test_invalid_not_counted(tmp_path):
    class InvalidPhone(Phone):
        def attempt(self, reference, observation_s):
            data = super().attempt(reference, observation_s)
            data["integrity"] = "INCOMPLETE"
            return data
    phone = InvalidPhone()
    result = run_fixed_power(plan(), Cmw(), Gss(), phone, tmp_path/"run.json")
    assert result["status"] == "PAUSED"
    assert result["valid"] == 0
    assert phone.calls == 3
