"""Write a consistent report snapshot alongside the SQLite audit ledger."""
import csv
import json
from html import escape
from tempfile import NamedTemporaryFile

from .core import ERROR_M, PASS_COUNT, SATELLITES, SAMPLES, START_DBM, TTFF_S
from .presentation import quantity, reason_text, state_text

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
        values = {**row, "reason": reason_text(row.get("reason"))}
        cells = (escape(str(values[key]) if values.get(key) is not None else "—") for key, _ in COLUMNS)
        rows.append("<tr><td>" + "</td><td>".join(cells) + "</td></tr>")
    levels = "".join(
        f"<tr><td>{level['power_dbm']}</td><td>{escape(str(level['readback_dbm']))}</td>"
        f"<td>{level['pass_count']}/{level['valid_count']}</td><td>{level['invalid_count']}</td>"
        f"<td><span class=\"verdict {escape(level['status'])}\">{escape(state_text(level['status']))}</span></td></tr>"
        for level in report["levels"]
    )
    threshold = quantity(run["threshold_dbm"], "dBm")
    total = sum(level["valid_count"] for level in report["levels"])
    reason = reason_text(run["reason"])
    details = json.dumps({"config": run["config"], "evidence": run["evidence"]},
                         indent=2, ensure_ascii=False)
    config = run["config"]
    evidence = run["evidence"]
    fields = (
        ("场景", config["scenario_id"]), ("启动模式", config["startup_mode"]),
        ("校准引用", config["calibration_ref"]), ("功率定义", config["power_definition"]),
        ("手机", evidence.get("phone", {}).get("model")),
        ("LTE 小区", evidence.get("lte", {}).get("cell")),
    )
    overview = "".join(f"<div><dt>{name}</dt><dd>{escape(str(value or '—'))}</dd></div>" for name, value in fields)
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GNSS 灵敏度测试报告</title>
<style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{font:15px/1.6 "Microsoft YaHei UI",system-ui,sans-serif;
margin:0;background:#eef2f7;color:#17283e}}header{{background:#142941;color:white;padding:30px 0}}
.wrap{{width:min(1240px,calc(100% - 36px));margin:auto}}h1,h2,p,dl,dd{{margin:0}}
h1{{font-size:clamp(24px,4vw,36px)}}h2{{font-size:18px;margin-bottom:.75rem}}header p{{color:#c7d7eb}}
.badge{{display:inline-block;background:#29435f;border-radius:7px;padding:4px 10px;color:white;font-weight:bold;margin-top:10px}}
.badge.mock{{background:#493821;color:#ffe1a8}}main{{padding:18px 0 36px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:12px 0}}
.cards div,.panel{{background:white;border:1px solid #d6e0eb;border-radius:12px;padding:16px}}
.cards dt,dt{{color:#50647b}}.cards dd{{font-size:24px;font-weight:bold}}.panel{{margin-top:12px}}
.context{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px 24px}}
.context dd{{overflow-wrap:anywhere}}.files{{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px}}
a{{color:#1956a5}}a:focus-visible,summary:focus-visible{{outline:2px solid #1956a5}}
.table-scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
td,th{{border-bottom:1px solid #d6e0eb;padding:8px 10px;text-align:left;white-space:nowrap}}
th{{background:#e6eef7}}tbody tr:nth-child(even){{background:#f3f7fb}}
.verdict{{display:inline-block;border-radius:5px;background:#e6eef7;padding:1px 7px}}
.verdict.PASS{{background:#daefe6;color:#12634c}}.verdict.FAIL{{background:#f8e2dd;color:#9d3328}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}}summary{{cursor:pointer}}
@media print{{body,header,.panel,.cards div{{background:white;color:#17283e}}header p{{color:#50647b}}
th,td{{white-space:normal;overflow-wrap:anywhere;padding:4px;font-size:9pt}}thead{{display:table-header-group}}
tr{{break-inside:avoid}}}}
</style>
<header><div class="wrap"><h1>GNSS 灵敏度测试报告</h1>
<p>{escape(run['id'])} · {escape(run['started_utc'])}</p>
<span class="badge {'mock' if config['mock'] else ''}">{escape(report['mode'])}</span></div></header>
<main class="wrap">
<dl class="cards"><div><dt>运行状态</dt><dd>{escape(state_text(run['status']))}</dd></div>
<div><dt>最后通过档</dt><dd>{escape(threshold)}</dd></div><div><dt>有效试验</dt><dd>{total}</dd></div>
<div><dt>INVALID</dt><dd>{report['invalid_count']}</dd></div></dl>
<section class="panel"><h2>运行摘要</h2><p>{escape(reason)}</p><dl class="context">{overview}</dl>
<div class="files"><a href="report.csv">逐次数据 CSV</a><a href="report.json">完整记录 JSON</a>
<a href="{escape(report['audit_path'], quote=True)}">审计数据库 SQLite</a></div></section>
<section class="panel"><h2>功率档位</h2>
<p>每档 {SAMPLES} 次有效试验，至少 {PASS_COUNT} 次 PASS。单次标准为 TTFF ≤ {TTFF_S} s、水平误差 ≤ {ERROR_M} m、参与解算卫星数 ≥ {SATELLITES}。</p>
<div class="table-scroll"><table><thead><tr><th scope="col">设定 (dBm)</th><th scope="col">读回 (dBm)</th>
<th scope="col">成功 / 有效</th><th scope="col">INVALID</th><th scope="col">状态</th></tr></thead>
<tbody>{levels}</tbody></table></div></section>
<section class="panel"><h2>试验明细</h2><div class="table-scroll" tabindex="0" aria-label="试验明细">
<table><thead><tr>{columns}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section class="panel"><details><summary>查看完整配置与设备证据</summary><pre>{escape(details)}</pre></details></section>
<section class="panel"><h2>验证限制</h2><ul>{''.join(f'<li>{escape(item)}</li>' for item in report['limitations'])}</ul></section>
</main>
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
