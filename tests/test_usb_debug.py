from desktop.usb_debug import exchange
from desktop.protocol import envelope
from desktop.core import LinkError
import pytest


class Transport:
    def send_command(self, request):
        self.request = request

    def receive_event(self):
        return envelope("DEVICE_STATUS", self.request["run_id"],
                        self.request["attempt_id"],
                        {"response_to": self.request["message_id"], "ready": True})


def test_debug_exchange():
    assert exchange(Transport(), "debug", "HELLO", 1)["ready"]


def test_debug_rejects_wrong_response():
    class Wrong(Transport):
        def receive_event(self):
            return envelope("DEVICE_STATUS", "other", payload={"response_to": "wrong"})
    with pytest.raises(LinkError):
        exchange(Wrong(), "debug", "PING", 1)
