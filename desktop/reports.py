"""Write a consistent report snapshot alongside the SQLite audit ledger."""
import csv
import json
from html import escape
from tempfile import NamedTemporaryFile

from .core import ERROR_M, PASS_COUNT, SATELLITES, SAMPLES, START_DBM, TTFF_S

COLUMNS = (
    ("power_dbm", "设定功率 (dBm)"), ("readback_dbm", "档位读回 (dBm)"), ("ordinal", "轮次"),
    ("id", "试验 ID"), ("status", "结果"), ("reason", "原因"), ("ttff_s", "TTFF (s)"),
    ("horizontal_error_m", "水平误差 (m)"), ("used_in_fix", "参与解算卫星"),
    ("latitude", "纬度"), ("longitude", "经度"), ("t0_monotonic_ns", "t0 (ns)"),
    ("first_fix_elapsed_realtime_ns", "首次定位 (ns)"), ("satellite_elapsed_ns", "卫星记录 (ns)"),
    ("satellite_association", "卫星关联"), ("started_utc", "开始 (UTC)"),
)


def snapshot(store, run_id):
    run = store.run(run_id)
    levels = store.levels(run_id)
    for level in levels:
        attempts = store.attempts(level["id"])
        level["attempts"] = attempts
        level["valid_count"] = sum(row["status"] in {"PASS", "FAIL"} for row in attempts)
        level["pass_count"] = sum(row["status"] == "PASS" for row in attempts)
        level["invalid_count"] = sum(row["status"] == "INVALID" for row in attempts)
    mock = run["config"]["mock"]
    return {
        "report_version": 1,
        "mode": "MOCK / 合成数据" if mock else "USB ADB TCP / 现场人工仪器确认",
        "run": run, "levels": levels,
        "invalid_count": sum(level["invalid_count"] for level in levels),
        "criteria": {"start_dbm": START_DBM, "step_db": -1, "samples": SAMPLES, "passes": PASS_COUNT,
                     "ttff_s_max": TTFF_S, "horizontal_error_m_max": ERROR_M, "used_in_fix_min": SATELLITES},
        "audit_path": store.path.name,
        "limitations": [
            "合成设备与定位，仅用于流程验证。" if mock else "仪器证据为现场人工记录。",
            "SimREPLAYplus 与 CMW500 远控接口待按现场版本验证。",
            "使用配置所述功率定义和参考平面。正式阈值需评估 USB 对 GNSS 的影响。",
            "Android 卫星关联与启动状态须经目标机型现场验证。",
        ],
        "events": store.events(run_id),
        "device_logs": store.logs(run_id),
    }


def _rows(report):
    for level in report["levels"]:
        for attempt in level["attempts"]:
            yield {**attempt["metrics"], **attempt, "power_dbm": level["power_dbm"],
                   "readback_dbm": level["readback_dbm"]}


def _html(report):
    run = report["run"]
    columns = "".join(f"<th>{escape(label)}</th>" for _, label in COLUMNS)
    rows = []
    for row in _rows(report):
        cells = (escape(str(row.get(key) if row.get(key) is not None else "")) for key, _ in COLUMNS)
        rows.append("<tr><td>" + "</td><td>".join(cells) + "</td></tr>")
    levels = "".join(
        f"<tr><td>{level['power_dbm']}</td><td>{escape(str(level['readback_dbm']))}</td>"
        f"<td>{level['pass_count']}/{level['valid_count']}</td><td>{level['invalid_count']}</td>"
        f"<td>{escape(level['status'])}</td></tr>" for level in report["levels"]
    )
    threshold = "—" if run["threshold_dbm"] is None else f"{run['threshold_dbm']} dBm"
    reason = "未在起始档通过" if run["reason"] == "NOT_PASSED_AT_START" else str(run["reason"])
    details = json.dumps({"config": run["config"], "evidence": run["evidence"]},
                         indent=2, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="UTF-8"><title>GNSS 灵敏度测试报告</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;margin:2rem;color:#182235}}
table{{border-collapse:collapse}}td,th{{border:1px solid #c6cfdb;padding:.4rem;text-align:left}}
th{{background:#e9eff6}}pre{{white-space:pre-wrap}}section{{overflow:auto}}
</style>
<h1>GNSS 灵敏度测试报告</h1>
<p><strong>{escape(report['mode'])}</strong> · {escape(run['id'])} · {escape(run['started_utc'])}</p>
<p>状态 {escape(run['status'])} · 原因 {escape(reason)} · 最后通过档 {threshold} · INVALID {report['invalid_count']}</p>
<p>每档 20 次有效试验，至少 19 次 PASS。单次标准为 TTFF ≤ 20.3 s、水平误差 ≤ 101.3 m、参与解算卫星数 ≥ 4。</p>
<p>原始事件与设备操作日志保存在 <a href="{escape(report['audit_path'], quote=True)}">{escape(report['audit_path'])}</a>。
  完整记录见 <a href="report.json">JSON</a>，逐次数据见 <a href="report.csv">CSV</a>。</p>
<h2>功率档位</h2><table><thead><tr><th>设定 (dBm)</th><th>读回 (dBm)</th><th>成功 / 有效</th>
<th>INVALID</th><th>状态</th></tr></thead><tbody>{levels}</tbody></table>
<h2>试验明细</h2><section><table><thead><tr>{columns}</tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<h2>配置与设备证据</h2><pre>{escape(details)}</pre>
<h2>验证限制</h2><ul>{''.join(f'<li>{escape(item)}</li>' for item in report['limitations'])}</ul>
</html>"""


def _write_csv(report, file):
    writer = csv.writer(file)
    writer.writerow([key for key, _ in COLUMNS])
    for row in _rows(report):
        values = []
        for key, _ in COLUMNS:
            value = row.get(key)
            # Prevent spreadsheet formula evaluation of external text fields.
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)


def export(store, run_id):
    report = snapshot(store, run_id)
    result = store.path.parent
    writers = {
        "report.csv": lambda file: _write_csv(report, file),
        "report.json": lambda file: json.dump(report, file, ensure_ascii=False, allow_nan=False, indent=2),
        "report.html": lambda file: file.write(_html(report)),
    }
    from pathlib import Path
    for name, write in writers.items():
        with NamedTemporaryFile(mode="w", encoding="utf-8-sig" if name.endswith(".csv") else "utf-8",
                                newline="", dir=result, delete=False) as file:
            temporary = Path(file.name)
            try:
                write(file)
            except Exception:
                file.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.replace(result / name)
        finally:
            temporary.unlink(missing_ok=True)
    return result / "report.html"
