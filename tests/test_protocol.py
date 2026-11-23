import json
import socket
from threading import Thread

import pytest

from desktop.core import LinkError, RunConfig
from desktop.mock import Faults, MockPhone
from desktop.protocol import decode, dump, envelope
from desktop.storage import Store
from desktop.transports import AdbTransport


def test_v1_envelope():
    message = envelope("START_ATTEMPT", "run", "attempt")
    assert decode((dump(message) + "\n").encode()) == message
    for invalid in (message | {"protocol_version": 2}, message | {"attempt_id": None},
                    message | {"seq": -1}, message | {"utc_timestamp": "yesterday"}):
        with pytest.raises(LinkError):
            decode((dump(invalid) + "\n").encode())
    with pytest.raises(LinkError):
        decode(dump(message).encode())


def test_idempotent_command_and_replay():
    phone = MockPhone(Faults())
    phone.connect()
    config = RunConfig(-120, 1)
    for kind in ("CONFIGURE_RUN", "PREPARE_ATTEMPT"):
        phone.send_command(envelope(kind, "run", "attempt"))
        phone.receive_event()
    command = envelope("START_ATTEMPT", "run", "attempt",
                       {"power_dbm": -120, "reference": config.reference, "observation_s": 30})
    phone.send_command(command)
    reply = phone.receive_event()
    phone.reconnect()
    phone.send_command(command)
    assert phone.receive_event() == reply
    phone.send_command(envelope("FETCH_EVENTS", "run", payload={"last_ack_seq": 0}))
    events = phone.receive_event()["payload"]["events"]
    assert len([event for event in events if event["type"] == "ATTEMPT_RESULT"]) == 1
    with pytest.raises(LinkError):
        phone.send_command(command | {"seq": 21})


def test_ledger_dedup_and_rejects_conflict(tmp_path):
    with Store(tmp_path / "run.sqlite") as store:
        run = store.create_run(RunConfig(-120, 1))
        event = envelope("ATTEMPT_RESULT", run, "attempt", seq=12)
        store.record_phone(event)
        store.record_phone(event)
        assert store.cursor(run) == 12
        assert len(store.events(run)) == 1
        with pytest.raises(LinkError):
            store.record_phone(event | {"payload": {"different": True}})


def test_adb_local_forward_and_bidirectional_jsonl(monkeypatch):
    calls = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(5)
        port = listener.getsockname()[1]
        transport = AdbTransport("fixture")

        def adb(*args, serial=None):
            calls.append((args, serial))
            if args[0] == "devices":
                return "List of devices attached\nfixture device usb:1 model:DUT"
            if args[0] == "forward":
                return str(port)
            raise AssertionError(args)

        def receive():
            with listener.accept()[0] as client, client.makefile("rb") as stream:
                client.settimeout(5)
                request = json.loads(stream.readline())
                reply = envelope("DEVICE_STATUS", request["run_id"], payload={"ready": True})
                client.sendall((dump(reply) + "\n").encode())

        monkeypatch.setattr(transport, "_run_adb", adb)
        server = Thread(target=receive)
        server.start()
        try:
            transport.connect()
            transport.send_command(envelope("HELLO", "run"))
            assert transport.receive_event()["payload"]["ready"] is True
        finally:
            transport.disconnect()
            server.join(6)
        assert not server.is_alive()
        assert (("forward", "tcp:0", "tcp:18765"), "fixture") in calls
        assert (("forward", "--remove", f"tcp:{port}"), "fixture") in calls
