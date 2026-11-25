from time import monotonic

from .core import DeviceError, LinkError
from .instruments import audited
from .protocol import EVENTS, envelope, validate


class PhoneSession:
    def __init__(self, transport, store, run, notify):
        self.transport = transport
        self.store = store
        self.run = run
        self.notify = notify
        self.sequence = 0

    def command(self, kind, attempt=None, payload=None):
        self.sequence += 1
        request = envelope(kind, self.run, attempt, payload, self.sequence)

        def exchange():
            self.transport.send_command(request)
            response = validate(self.transport.receive_event())
            data = response["payload"]
            if (response["run_id"] != self.run or response["attempt_id"] != attempt
                    or response["seq"] != 0 or data.get("response_to") != request["message_id"]):
                raise LinkError("手机响应与请求不匹配")
            if response["type"] == "ERROR":
                raise DeviceError(data.get("reason", "PHONE_ERROR"))
            if response["type"] != "DEVICE_STATUS":
                raise LinkError("手机响应类型错误")
            return response

        # Raw telemetry belongs to the event table. Keep only batch count in device logs.
        if kind == "FETCH_EVENTS":
            start = monotonic()
            try:
                reply = exchange()
            except DeviceError as exc:
                self.store.device_log(self.run, "phone", kind, request, str(exc), monotonic() - start,
                                      "ERROR", request["utc_timestamp"])
                raise
            events = reply["payload"].get("events")
            info = {**reply, "payload": {"count": len(events) if isinstance(events, list) else None}}
            self.store.device_log(self.run, "phone", kind, request, info, monotonic() - start,
                                  "OK", request["utc_timestamp"])
            return reply["payload"]
        return audited(self.store, self.run, "phone", kind, lambda _: exchange(), request)["payload"]

    def drain(self, limit=30, check=lambda: None):
        for _ in range(limit):
            check()
            cursor = self.store.cursor(self.run)
            events = self.command("FETCH_EVENTS", payload={"last_ack_seq": cursor}).get("events")
            if not isinstance(events, list):
                raise LinkError("补传缺少事件列表")
            if not events:
                return
            previous = 0
            for event in events:
                validate(event)
                seq = event["seq"]
                if (event["run_id"] != self.run or event["type"] not in EVENTS
                        or seq == 0 or seq <= previous):
                    raise LinkError("补传事件的运行、类型或序列错误")
                self.store.record_phone(event)
                previous = seq
                if seq > cursor:
                    self.notify(event["type"], event)
                    yield event
            if previous <= cursor:
                raise LinkError("补传未推进游标")
            self.command("ACK", payload={"seq": previous})
        raise LinkError("补传批次超限")
