"""Deterministic synthetic devices and one-shot or repeated fault injection."""
from collections import Counter
from uuid import uuid4

from geographiclib.geodesic import Geodesic

from .core import DeviceError, LinkError
from .protocol import envelope
from .transports import PhoneTransport
from .instruments import SimulatorAdapter, CellularAdapter

FAULTS = ("gss_connect", "gss_set_power", "gss_readback", "gss_stop", "lte_unregistered",
          "phone_connect", "phone_prepare", "phone_health", "no_satellite", "disconnect",
          "drop_ack", "hold_attempt", "late_fix", "position_error", "few_satellites", "timeout")


class Faults:
    def __init__(self, names=()):
        self.remaining = Counter(names)
        if unknown := self.remaining.keys() - set(FAULTS):
            raise ValueError(f"未知注入点: {sorted(unknown)}")

    def take(self, name):
        if self.remaining[name] > 0:
            self.remaining[name] -= 1
            return True
        return False


class MockSimulator(SimulatorAdapter):
    mock = True

    def __init__(self, config, faults):
        self.config = config
        self.faults = faults
        self.running = False
        self.power = None

    def connect(self):
        if self.faults.take("gss_connect"):
            raise DeviceError("MOCK_GSS_CONNECT")
        return {"control": "MOCK"}

    def identify(self):
        return {"model": "Mock GSS7000", "software": "SimREPLAYplus Mock", "version": "1"}

    def verify_scenario(self, config):
        return {"scenario_id": self.config.scenario_id, "scenario_hash": self.config.scenario_hash,
                "static": True, "reference": self.config.reference,
                "signals": self.config.scenario_signals, "calibration_ref": self.config.calibration_ref,
                "power_definition": self.config.power_definition}

    def start(self):
        self.running = True
        return {"running": True}

    def set_power(self, power_dbm):
        if self.faults.take("gss_set_power"):
            raise DeviceError("MOCK_GSS_SET_POWER")
        self.power = power_dbm
        return {"set_power_dbm": power_dbm}

    def read_power(self):
        return {"readback_dbm": self.power + int(self.faults.take("gss_readback"))}

    def get_state(self):
        return {"running": self.running, "scenario_hash": self.config.scenario_hash, "power_dbm": self.power}

    def safe_stop(self):
        if self.faults.take("gss_stop"):
            raise DeviceError("MOCK_GSS_STOP")
        self.running = False
        return {"running": False, "rf_off": True}


class MockCellular(CellularAdapter):
    mock = True

    def __init__(self, faults):
        self.faults = faults
        self.evidence = None

    def connect(self):
        return {"control": "MOCK", "model": "Mock CMW500"}

    def verify_lte_environment(self):
        self.evidence = {"model": "Mock CMW500", "firmware": "1", "options": "MOCK",
                         "registered": not self.faults.take("lte_unregistered"),
                         "cell": "synthetic", "band": "synthetic", "dut": "synthetic",
                         "evidence": "synthetic LTE registration"}
        return self.evidence

    def capture_evidence(self):
        return self.evidence


class MockPhone(PhoneTransport):
    mock = True

    def __init__(self, faults, passing_through=-121):
        self.faults = faults
        self.passing_through = passing_through
        self.connected = False
        self.active_run = None
        self.active = None
        self.prepared = None
        self.cached = {}
        self.events = []
        self.acked = {}
        self.started = set()
        self.reply = None
        self.instance = str(uuid4())

    def connect(self):
        if self.faults.take("phone_connect"):
            raise LinkError("MOCK_PHONE_CONNECT")
        self.connected = True

    def disconnect(self):
        self.connected = False
        self.reply = None

    def status(self):
        return {"ready": True, "local_stop": False, "active_run": self.active_run,
                "active_attempt": self.active, "model": "Mock Android", "app_version": "1",
                "instance_id": self.instance}

    def event(self, kind, run, attempt, data, time=None):
        self.events.append(envelope(kind, run, attempt, data, len(self.events) + 1, time))

    def send_command(self, command):
        if not self.connected:
            raise LinkError("MOCK_DISCONNECTED")
        message_id = command["message_id"]
        if message_id in self.cached:
            previous, self.reply = self.cached[message_id]
            if command != previous:
                raise LinkError("MOCK_DUPLICATE_ID_CONFLICT")
            return
        kind, run, attempt = (command[key] for key in ("type", "run_id", "attempt_id"))
        args = command["payload"]
        response, error = {}, None
        if kind in {"HELLO", "GET_STATUS", "PING"}:
            response = self.status()
            if kind == "PING" and self.faults.take("phone_health"):
                response["ready"] = False
        elif kind == "CONFIGURE_RUN":
            self.active_run = run
        elif kind == "PREPARE_ATTEMPT":
            self.prepared = attempt
            if self.faults.take("phone_prepare"):
                error = "MOCK_PHONE_PREPARE"
        elif kind == "START_ATTEMPT":
            if self.prepared != attempt or attempt in self.started:
                error = "MOCK_NOT_PREPARED"
            else:
                self.started.add(attempt)
                self.active = attempt
                self.prepared = None
                if not self.faults.take("hold_attempt"):
                    self._result(run, attempt, args)
                    self.active = None
                if self.faults.take("disconnect"):
                    self.disconnect()
                    raise LinkError("MOCK_LINK_DROPPED_AFTER_START")
        elif kind in {"STOP_ATTEMPT", "STOP_RUN"}:
            if self.active and self.active_run == run and (kind == "STOP_RUN" or self.active == attempt):
                self.event("ATTEMPT_RESULT", run, self.active, {"integrity": "INVALID", "reason": "USER_STOP"})
                self.active = None
            if kind == "STOP_RUN" or self.prepared == attempt:
                self.prepared = None
        elif kind == "FETCH_EVENTS":
            response = {"events": [event for event in self.events
                                   if event["run_id"] == run and event["seq"] > args["last_ack_seq"]][:24]}
        elif kind == "ACK":
            if self.faults.take("drop_ack"):
                self.disconnect()
                raise LinkError("MOCK_LINK_DROPPED_AT_ACK")
            self.acked[run] = max(self.acked.get(run, 0), args["seq"])
        self.reply = envelope("ERROR" if error else "DEVICE_STATUS", run, attempt,
                              {**response, "response_to": message_id, **({"reason": error} if error else {})})
        if kind in {"CONFIGURE_RUN", "PREPARE_ATTEMPT", "START_ATTEMPT", "STOP_ATTEMPT", "STOP_RUN"}:
            self.cached[message_id] = (command, self.reply)

    def receive_event(self):
        if self.reply is None or not self.connected:
            raise LinkError("MOCK_NO_RESPONSE")
        reply, self.reply = self.reply, None
        return reply

    def _result(self, run, attempt, args):
        t0 = (len(self.events) + 1) * 100_000_000_000
        self.event("DEVICE_STATUS", run, attempt, {"t0_monotonic_ns": t0}, t0)
        if self.faults.take("timeout"):
            self.event("ATTEMPT_RESULT", run, attempt, {
                "status": "FAIL", "integrity": "COMPLETE", "reason": "TIMEOUT", "t0_monotonic_ns": t0,
            })
            return
        late = self.faults.take("late_fix") or args["power_dbm"] < self.passing_through
        ttff = min(args["observation_s"], 21.0) if late else 8.0
        if late and ttff <= 20.3:
            self.event("ATTEMPT_RESULT", run, attempt, {
                "status": "FAIL", "integrity": "COMPLETE", "reason": "TIMEOUT", "t0_monotonic_ns": t0,
            })
            return
        distance = 102.0 if self.faults.take("position_error") else 9.0
        reference = args["reference"]
        position = Geodesic.WGS84.Direct(reference["latitude"], reference["longitude"], 45, distance)
        fix = t0 + round(ttff * 1e9)
        used = 3 if self.faults.take("few_satellites") else 7
        metrics = {"source": "GPS_PROVIDER", "synthetic": True, "latitude": position["lat2"],
                   "longitude": position["lon2"], "first_fix_elapsed_realtime_ns": fix}
        if not self.faults.take("no_satellite"):
            self.event("SATELLITE_STATUS", run, attempt, {"used_in_fix": used, "synthetic": True}, fix)
            metrics.update(used_in_fix=used, satellite_elapsed_ns=fix, satellite_association="MOCK")
        self.event("LOCATION_UPDATE", run, attempt, metrics, fix)
        self.event("FIRST_FIX", run, attempt, metrics, fix)
        self.event("ATTEMPT_RESULT", run, attempt, {**metrics, "t0_monotonic_ns": t0,
                   "integrity": "COMPLETE", "status": "OBSERVED", "reason": "FIRST_FIX"}, fix)


def mock_devices(config, faults=None, passing_through=-121):
    faults = faults if faults is not None else Faults()
    return MockSimulator(config, faults), MockCellular(faults), MockPhone(faults, passing_through)
