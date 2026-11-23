"""SQLite run ledger. Events are committed before the phone is acknowledged."""
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
import json

from .protocol import dump, utc
from .core import RunConfig, LinkError

SCHEMA_VERSION = 1
MIGRATIONS = {
    1: """
        CREATE TABLE run(
            id TEXT PRIMARY KEY, started_utc TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL,
            reason TEXT, threshold_dbm INTEGER, evidence TEXT NOT NULL
        );
        CREATE TABLE level(
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES run(id), power_dbm INTEGER NOT NULL,
            readback_dbm REAL, status TEXT NOT NULL, UNIQUE(run_id, power_dbm)
        );
        CREATE TABLE attempt(
            id TEXT PRIMARY KEY, level_id TEXT NOT NULL REFERENCES level(id), ordinal INTEGER NOT NULL,
            started_utc TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, metrics TEXT NOT NULL,
            UNIQUE(level_id, ordinal)
        );
        CREATE TABLE event(
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES run(id), attempt_id TEXT,
            source TEXT NOT NULL, seq INTEGER, message_id TEXT, event_type TEXT NOT NULL,
            utc_timestamp TEXT NOT NULL, monotonic_ns INTEGER, payload TEXT NOT NULL,
            UNIQUE(run_id, source, seq), UNIQUE(run_id, message_id)
        );
        CREATE TABLE device_log(
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES run(id), device TEXT NOT NULL,
            operation TEXT NOT NULL, request TEXT NOT NULL, response TEXT NOT NULL,
            duration_ms REAL NOT NULL, outcome TEXT NOT NULL, timestamp_utc TEXT NOT NULL
        );
    """,
}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self.close()
            raise ValueError(f"数据库版本 {version} 高于本程序支持的版本")
        for step in range(version + 1, SCHEMA_VERSION + 1):
            self.db.executescript(f"BEGIN IMMEDIATE; {MIGRATIONS[step]} PRAGMA user_version = {step}; COMMIT;")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.db.close()

    @contextmanager
    def claim(self):
        # The ledger is owned by a run folder. A second process must not drive the same run.
        path = self.path.with_suffix(".lock.sqlite")
        with sqlite3.connect(path, timeout=0) as lock:
            lock.execute("BEGIN EXCLUSIVE")
            yield

    def create_run(self, config):
        run = str(uuid4())
        with self.db:
            self.db.execute("INSERT INTO run VALUES(?,?,?,?,?,?,?)",
                            (run, utc(), dump(asdict(config)), "IDLE", None, None, "{}"))
        return run

    def run(self, run_id):
        row = self.db.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("找不到运行记录")
        return self._parse(row, "config", "evidence")

    def history(self):
        return [self._parse(row, "config", "evidence")
                for row in self.db.execute("SELECT * FROM run ORDER BY started_utc DESC")]

    def config(self, run_id):
        return RunConfig(**self.run(run_id)["config"])

    def state(self, run_id, state, reason=None):
        with self.db:
            self.db.execute("UPDATE run SET status=?, reason=? WHERE id=?", (state, reason, run_id))
            self.db.execute("""INSERT INTO event(run_id,source,event_type,utc_timestamp,payload)
                               VALUES(?,?,?,?,?)""",
                            (run_id, "host", "STATE", utc(), dump({"state": state, "reason": reason})))

    def evidence(self, run_id, **new):
        current = self.run(run_id)["evidence"]
        with self.db:
            self.db.execute("UPDATE run SET evidence=? WHERE id=?", (dump(current | new), run_id))

    def levels(self, run_id):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM level WHERE run_id=? ORDER BY power_dbm DESC", (run_id,))]

    def level(self, run_id, power):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO level VALUES(?,?,?,?,?)",
                            (str(uuid4()), run_id, power, None, "OPEN"))
        return dict(self.db.execute("SELECT * FROM level WHERE run_id=? AND power_dbm=?",
                                    (run_id, power)).fetchone())

    def readback(self, level, value):
        with self.db:
            self.db.execute("UPDATE level SET readback_dbm=? WHERE id=?", (value, level))

    def close_level(self, run, level, power, passed):
        with self.db:
            self.db.execute("UPDATE level SET status=? WHERE id=?", ("PASS" if passed else "FAIL", level))
            if passed:
                self.db.execute("UPDATE run SET threshold_dbm=? WHERE id=?", (power, run))

    def attempts(self, level):
        return [self._parse(row, "metrics") for row in self.db.execute(
            "SELECT * FROM attempt WHERE level_id=? ORDER BY ordinal", (level,))]

    def create_attempt(self, level):
        attempt = str(uuid4())
        with self.db:
            self.db.execute("""INSERT INTO attempt VALUES(?,?,
                (SELECT COALESCE(MAX(ordinal),0)+1 FROM attempt WHERE level_id=?),?,'OPEN',NULL,'{}')""",
                (attempt, level, level, utc()))
        return attempt

    def decision(self, attempt, result):
        with self.db:
            changed = self.db.execute(
                "UPDATE attempt SET status=?, reason=?, metrics=? WHERE id=? AND status='OPEN'",
                (result["status"], result["reason"], dump(result), attempt)).rowcount
            if changed != 1:
                raise RuntimeError("Attempt already finalized")

    def invalidate_open(self, run_id, reason):
        with self.db:
            self.db.execute("""UPDATE attempt SET status='INVALID', reason=?, metrics=?
                WHERE status='OPEN' AND level_id IN (SELECT id FROM level WHERE run_id=?)""",
                (reason, dump({"status": "INVALID", "reason": reason}), run_id))

    def cursor(self, run_id):
        return self.db.execute("SELECT COALESCE(MAX(seq),0) FROM event WHERE run_id=? AND source='phone'",
                               (run_id,)).fetchone()[0]

    def record_phone(self, event):
        with self.db:
            try:
                self.db.execute("""INSERT INTO event(run_id,attempt_id,source,seq,message_id,event_type,
                    utc_timestamp,monotonic_ns,payload) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (event["run_id"], event["attempt_id"], "phone", event["seq"], event["message_id"],
                     event["type"], event["utc_timestamp"], event.get("monotonic_ns"), dump(event["payload"])))
            except sqlite3.IntegrityError as exc:
                previous = self.db.execute("""SELECT * FROM event WHERE run_id=? AND source='phone'
                    AND (seq=? OR message_id=?)""",
                    (event["run_id"], event["seq"], event["message_id"])).fetchone()
                if previous is None or any(previous[db_key] != value for db_key, value in (
                    ("seq", event["seq"]), ("message_id", event["message_id"]),
                    ("attempt_id", event["attempt_id"]), ("event_type", event["type"]),
                    ("utc_timestamp", event["utc_timestamp"]), ("monotonic_ns", event.get("monotonic_ns")),
                    ("payload", dump(event["payload"])),
                )):
                    raise LinkError("手机事件序列或消息 ID 冲突") from exc

    def events(self, run_id):
        return [self._parse(row, "payload") for row in self.db.execute(
            "SELECT * FROM event WHERE run_id=? ORDER BY id", (run_id,))]

    def device_log(self, run, device, operation, args, response, elapsed, outcome, timestamp):
        def serial(value):
            return json.dumps(value, default=str, ensure_ascii=False)
        with self.db:
            self.db.execute("""INSERT INTO device_log(run_id,device,operation,request,response,duration_ms,
                outcome,timestamp_utc) VALUES(?,?,?,?,?,?,?,?)""",
                (run, device, operation, serial(args), serial(response), elapsed * 1000, outcome, timestamp))

    def logs(self, run_id):
        return [self._parse(row, "request", "response") for row in self.db.execute(
            "SELECT * FROM device_log WHERE run_id=? ORDER BY id", (run_id,))]

    @staticmethod
    def _parse(row, *keys):
        result = dict(row)
        for key in keys:
            result[key] = json.loads(result[key])
        return result
