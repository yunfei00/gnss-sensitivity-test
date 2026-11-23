import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .core import LinkError

MAX_LINE = 1024 * 1024
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "protocol/v1.schema.json").read_text(encoding="utf-8"))
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def _date_time(value):
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return False
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FORMATS)
EVENTS = {"DEVICE_STATUS", "SATELLITE_STATUS", "LOCATION_UPDATE", "FIRST_FIX",
          "ATTEMPT_RESULT", "ERROR", "HEARTBEAT"}


def utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def envelope(kind, run, attempt=None, payload=None, seq=0, monotonic_ns=None):
    message = {
        "protocol_version": 1, "type": kind, "run_id": run, "attempt_id": attempt,
        "message_id": str(uuid4()), "seq": seq, "utc_timestamp": utc(),
        "payload": {} if payload is None else payload,
    }
    if monotonic_ns is not None:
        message["monotonic_ns"] = monotonic_ns
    return message


def dump(message):
    return json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def validate(message):
    error = next(VALIDATOR.iter_errors(message), None)
    if error is not None:
        raise LinkError(f"协议 v1 拒绝消息 ({error.json_path}: {error.message})")
    return message


def decode(line):
    if not line or not line.endswith(b"\n") or len(line) > MAX_LINE:
        raise LinkError("JSONL 消息缺失、不完整或过大")
    try:
        message = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise LinkError("无法解析 UTF-8 JSONL 消息") from exc
    return validate(message)


def _reject_constant(value):
    raise ValueError(value)
