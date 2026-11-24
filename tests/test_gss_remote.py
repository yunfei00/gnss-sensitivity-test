import socket
from threading import Thread
import pytest
from desktop.gss_remote import exchange, render_command
from desktop.core import DeviceError


def test_tcp_probe():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        def reply():
            with server.accept()[0] as client:
                assert client.makefile("rb").readline() == b"QUERY\n"
                client.sendall(b"OK\r\n")
        worker = Thread(target=reply)
        worker.start()
        try:
            assert exchange("127.0.0.1", server.getsockname()[1], "QUERY", b"\n", b"\r\n") == "OK\r\n"
        finally:
            worker.join(4)


def test_unconfigured_and_parameterized():
    with pytest.raises(DeviceError):
        render_command("")
    assert render_command("SET {value}", -120) == "SET -120"
    with pytest.raises(DeviceError):
        render_command("SET", -120)
