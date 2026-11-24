import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from desktop.stage45_gui import Stage45Page


def test_stage45_page_has_real_hardware_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    page = Stage45Page(SimpleNamespace())
    try:
        assert page.p4.text().startswith("开始 P4")
        assert page.p5.text().startswith("开始 P5")
        assert "gss_host" in page.fields
        assert "cmw_host" in page.fields
        assert "calibration" in page.fields
        assert "reference_db" in page.fields
        assert "range_min" in page.fields
        assert page.cancel.isEnabled() is False
    finally:
        page.close()
