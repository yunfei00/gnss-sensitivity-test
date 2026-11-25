from desktop.stage5_sweep import SweepPlan, run_sensitivity_sweep
from test_stage4_fixed import Cmw, Gss, Phone


def plan():
    return SweepPlan(-122, 3, 0, 0, "real-scenario", "calibration-2026")


def test_p5_stops_at_first_failed_level_and_reports_last_pass(tmp_path):
    class PowerGss(Gss):
        power = -120
        def set_power_dbm(self, value):
            self.power = value
        def verify_power_dbm(self, value):
            return self.power == value

    class PowerPhone(Phone):
        power = -120
        def attempt(self, reference, observation_s):
            data = super().attempt(reference, observation_s)
            if self.power == -121:
                data["used_in_fix"] = 2
            return data

    current = {"power": -120}
    class SharedGss(PowerGss):
        def set_power_dbm(self, value):
            super().set_power_dbm(value)
            current["power"] = value
    class SharedPhone(PowerPhone):
        def attempt(self, reference, observation_s):
            self.power = current["power"]
            return super().attempt(reference, observation_s)

    result = run_sensitivity_sweep(plan(), Cmw, SharedGss, SharedPhone, tmp_path/"scan")
    assert result["status"] == "FINISHED"
    assert result["reason"] == "LEVEL_FAILED"
    assert result["threshold_dbm"] == -120
    assert [(x["power_dbm"], x["passed"]) for x in result["levels"]] == [(-120, 20), (-121, 0)]
    assert not (tmp_path/"scan"/"level_-122.json").exists()


def test_p5_no_valid_start_threshold(tmp_path):
    class BadPhone(Phone):
        def attempt(self, reference, observation_s):
            payload = super().attempt(reference, observation_s)
            payload["used_in_fix"] = 0
            return payload
    result = run_sensitivity_sweep(plan(), Cmw, Gss, BadPhone, tmp_path/"scan")
    assert result["reason"] == "NOT_PASSED_AT_START"
    assert result["threshold_dbm"] is None
    assert len(result["levels"]) == 1


def test_p5_prevents_overwriting_existing_runs(tmp_path):
    folder = tmp_path/"scan"
    folder.mkdir()
    (folder/"keep.txt").write_text("do not delete")
    import pytest
    with pytest.raises(FileExistsError):
        run_sensitivity_sweep(plan(), Cmw, Gss, Phone, folder)
    assert (folder/"keep.txt").read_text() == "do not delete"


def test_gnss_only_sweep_without_cmw(tmp_path):
    class SweepGss(Gss):
        def set_power_dbm(self, value):
            assert -122 <= value <= -120

    result = run_sensitivity_sweep(plan(), None, SweepGss, Phone, tmp_path / "gnss")
    assert result["status"] == "FINISHED"
    assert result["threshold_dbm"] == -122
    assert [x["power_dbm"] for x in result["levels"]] == [-120, -121, -122]
    assert all(x["passed"] == 20 for x in result["levels"])
    import json
    assert all(json.loads((tmp_path / "gnss" / x["file"]).read_text())["test_mode"] == "GNSS_ONLY"
               for x in result["levels"])
