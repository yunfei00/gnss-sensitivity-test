import csv
from desktop.stage4_fixed import FixedPowerPlan, run_fixed_power
from desktop.stage45_reports import export_stage45
from test_stage4_fixed import Cmw, Gss, Phone


def test_p4_exports_twenty_rows_and_html(tmp_path):
    plan = FixedPowerPlan(-120, 0, 0, "real-scenario", "calibration-2026")
    result = run_fixed_power(plan, Cmw(), Gss(), Phone(), tmp_path/"fixed.json")
    assert result["status"] == "FINISHED"
    html, csv_file = export_stage45(tmp_path)
    with csv_file.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 20
    assert all(row["status"] == "PASS" for row in rows)
    assert "P4 固定功率" in html.read_text(encoding="utf-8")
