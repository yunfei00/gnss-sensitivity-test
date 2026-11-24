"""Real USB/ADB phone adapter for P4/P5 using protocol v1 and SQLite event audit."""
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from .core import DeviceError, LinkError, RunConfig, UserStop
from .phone import PhoneSession
from .storage import Store
from .transports import AdbTransport


class UsbGnssAdapter:
    def __init__(self, usb, adb, db_path, preparation, log=None, stop=None):
        self.usb, self.adb = usb, adb
        self.db_path = Path(db_path)
        self.preparation = preparation
        self.stop = stop
        self.log = log or (lambda *_: None)
        self.transport = None
        self.store = None
        self.phone = None
        self.run_id = None
        self.prepared = None
        self.instance_id = None

    def preflight(self):
        self.usb.check()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.db_path)
        self.store.__enter__()
        try:
            config = RunConfig(-200, 1, scenario_id="field-gnss",
                               scenario_hash="field-gnss-audit",
                               calibration_ref="external-calibration",
                               scenario_signals="GPS", mock=False)
            self.run_id = self.store.create_run(config)
            self.transport = AdbTransport(self.usb, self.adb)
            self.transport.connect()
            self.phone = PhoneSession(self.transport, self.store, self.run_id,
                                      lambda kind, event: self.log(kind + " " + str(event.get("seq"))))
            hello = self.phone.command("HELLO")
            if hello.get("ready") is not True or not hello.get("instance_id"):
                raise DeviceError("手机定位服务未准备好")
            if hello.get("active_attempt") is not None:
                raise DeviceError("手机已有其他活动试验")
            self.instance_id = hello["instance_id"]
            self.phone.command("CONFIGURE_RUN", payload={"startup_mode": "HOT"})
            self.log("手机 HELLO: " + str(hello.get("device_id")))
        except Exception:
            self.stop_run()
            raise

    def prepare(self, mode):
        if self.phone is None:
            raise LinkError("手机未连接")
        if mode != "HOT":
            raise DeviceError("当前 USB 适配器仅实现 HOT；COLD/WARM/AGPS 需要额外现场准备步骤")
        status = self.phone.command("PING")
        if status.get("ready") is not True or status.get("active_attempt") is not None:
            raise DeviceError("手机仍在采集或 GNSS 未就绪，不能开始下一次 HOT")
        evidence = (self.preparation(mode) if self.preparation is not None else
                    "AUTO_HOT: prior attempt stopped; PING ready and no active_attempt; "
                    "Android GPS_PROVIDER registers a fresh attempt and monotonic t0; "
                    "GNSS aiding state is intentionally not reset")
        if not isinstance(evidence, str) or not evidence.strip():
            raise DeviceError("缺少本轮 HOT 启动准备证据")
        self.prepared = (str(uuid4()), evidence)

    def attempt(self, reference, observation_s):
        if self.prepared is None:
            raise DeviceError("本轮未执行准备")
        attempt_id, evidence = self.prepared
        self.prepared = None
        self.phone.command("PREPARE_ATTEMPT", attempt_id, {
            "startup_mode": "HOT", "preparation_evidence": evidence})
        self.phone.command("START_ATTEMPT", attempt_id, {
            "reference": reference,
            "observation_s": observation_s, "satellite_tolerance_ms": 1000})
        deadline = monotonic() + observation_s + 8
        while monotonic() < deadline:
            if self.stop is not None and self.stop.is_set():
                raise UserStop("USER_STOP")
            self.transport.check_connection()
            events = list(self.phone.drain(check=self.transport.check_connection))
            results = [event for event in events
                       if event["attempt_id"] == attempt_id and event["type"] == "ATTEMPT_RESULT"]
            if len(results) > 1:
                raise LinkError("收到重复试验最终结果")
            if results:
                payload = results[0]["payload"]
                self.phone.command("PING")
                return payload
            sleep(0.2)
        raise LinkError("未收到本轮 GNSS ATTEMPT_RESULT")

    def stop_run(self):
        ok = True
        try:
            if self.phone is not None:
                self.phone.command("STOP_RUN")
                status = self.phone.command("GET_STATUS")
                ok = status.get("active_attempt") is None
        except Exception as exc:
            self.log("STOP_RUN 失败: " + str(exc))
            ok = False
        finally:
            if self.transport is not None:
                try:
                    self.transport.disconnect()
                except Exception as exc:
                    self.log("USB 断开失败: " + str(exc))
                    ok = False
            if self.store is not None:
                self.store.__exit__(None, None, None)
            self.store = None
            self.phone = None
            self.transport = None
        return ok
