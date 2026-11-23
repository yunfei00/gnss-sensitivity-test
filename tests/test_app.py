import os
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from desktop.app import MainWindow


def wait_for(app, predicate, timeout=15):
    end = monotonic() + timeout
    while not predicate():
        assert monotonic() < end
        app.processEvents()
        sleep(0.01)
    app.processEvents()


def test_window_start_stop_resume_history(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.show()
    try:
        window.faults.setText("hold_attempt")
        window.start.click()
        wait_for(app, lambda: "ATTEMPT_RUNNING" in window.state.text())
        assert "CMW500 LTE" in window.devices.text()
        window.stop.click()
        wait_for(app, lambda: window.worker is None)
        assert "STOPPED" in window.state.text()
        assert window.history.count() == 1
        window.history.setCurrentRow(0)
        assert window.attempts.rowCount() == 1
        window.faults.clear()
        window.resume.click()
        wait_for(app, lambda: window.worker is None)
        assert "FINISHED" in window.state.text()
        assert "TTFF" in window.live.text()
        assert window.attempts.rowCount() == 61
        assert window.report.is_file()
    finally:
        if window.worker is not None:
            window.stop_run()
            window.worker.wait(5000)
            app.processEvents()
        window.close()
