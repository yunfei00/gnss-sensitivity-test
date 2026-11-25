"""P4/P5 static CSV and HTML reports from immutable per-attempt JSON evidence."""
import csv
import html
import json
from pathlib import Path


COLUMNS = ("level_dbm", "attempt", "status", "reason", "ttff_s",
           "horizontal_error_m", "used_in_fix", "utc")


def export_stage45(directory):
    directory = Path(directory)
    if (directory / "sweep.json").is_file():
        summary = json.loads((directory / "sweep.json").read_text(encoding="utf-8"))
        levels = summary.get("levels", [])
        sources = [(level["power_dbm"], directory / level["file"]) for level in levels]
    elif (directory / "fixed.json").is_file():
        summary = json.loads((directory / "fixed.json").read_text(encoding="utf-8"))
        sources = [(summary["plan"]["power_dbm"], directory / "fixed.json")]
    else:
        raise FileNotFoundError("找不到 P4/P5 测试记录")
    rows = []
    for power, path in sources:
        record = json.loads(path.read_text(encoding="utf-8"))
        for attempt in record.get("attempts", []):
            rows.append({
                "level_dbm": power, "attempt": attempt.get("number"),
                "status": attempt.get("status"), "reason": attempt.get("reason"),
                "ttff_s": attempt.get("ttff_s"),
                "horizontal_error_m": attempt.get("horizontal_error_m"),
                "used_in_fix": attempt.get("used_in_fix"),
                "utc": attempt.get("utc"),
            })
    csv_path = directory / "report.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    def esc(value):
        return html.escape(str(value if value is not None else ""))
    heading = "P5 灵敏度扫描" if "levels" in summary else "P4 固定功率 20 次"
    cells = "".join("<tr>" + "".join("<td>" + esc(row.get(k)) + "</td>" for k in COLUMNS) + "</tr>" for row in rows)
    summary_text = html.escape(json.dumps(
        {key: value for key, value in summary.items() if key not in ("attempts", "levels")},
        ensure_ascii=False, indent=2))
    markup = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
              '<title>GNSS P4/P5 报告</title><style>body{font-family:sans-serif;margin:2em}'
              'table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:6px}'
              'pre{white-space:pre-wrap}</style></head><body><h1>' + heading +
              '</h1><p>真实设备运行记录；功率绝对值以现场校准证据为准。</p><pre>' +
              summary_text + '</pre><table><thead><tr>' +
              ''.join('<th>' + esc(k) + '</th>' for k in COLUMNS) +
              '</tr></thead><tbody>' + cells + '</tbody></table></body></html>')
    html_path = directory / "report.html"
    html_path.write_text(markup, encoding="utf-8")
    return html_path, csv_path
