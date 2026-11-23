"""One run controller shared by the Windows UI and the Mock CLI."""
from math import isfinite
from threading import Event
from time import monotonic

from . import __version__
from .core import (INVALID_RETRIES, PASS_COUNT, SAMPLES, START_DBM, DeviceError, LinkError,
                   UserStop, evaluate, verified_readback)
from .instruments import audited
from .phone import PhoneSession


class TestEngine:
    __test__ = False

    def __init__(self, store, run_id, simulator, cellular, transport, stop=None, notify=None,
                 prepare=None):
        self.db = store
        self.run = run_id
        self.config = store.config(run_id)
        self.sim = simulator
        self.lte = cellular
        self.transport = transport
        self.stop = stop if stop is not None else Event()
        self.notify = notify if notify is not None else lambda *_: None
        self.prepare = prepare
        self.phone = PhoneSession(transport, store, run_id, self.notify)
        self.sim_owned = False
        self.link_touched = False
        self.phone_owned = False
        self.phone_instance = None
        if any(device.mock is not self.config.mock for device in (simulator, cellular, transport)):
            raise ValueError("Mock 与现场设备不可混用")
        if not self.config.mock and prepare is None:
            raise ValueError("现场运行必须提供每轮启动准备证据")

    def _state(self, state, reason=None):
        self.db.state(self.run, state, reason)
        self.notify("STATE", {"state": state, "reason": reason})

    def _check_stop(self):
        self.transport.check_connection()
        if self.stop.is_set():
            raise UserStop("USER_STOP")

    def _settle(self):
        end = monotonic() + self.config.settle_s
        while (remaining := end - monotonic()) > 0:
            self.stop.wait(min(remaining, 0.2))
            self._check_stop()

    def _device(self, adapter, operation, *args):
        name = "GSS7000" if adapter is self.sim else "CMW500"
        return audited(self.db, self.run, name, operation, getattr(adapter, operation), *args)

    def _link(self, operation):
        return audited(self.db, self.run, "phone", operation, getattr(self.transport, operation))

    def _lte(self):
        status = self._device(self.lte, "verify_lte_environment")
        previous = self.db.run(self.run)["evidence"].get("lte", {})
        if status.get("registered") is not True:
            raise DeviceError("CMW500 LTE 未注册")
        if previous and any(previous.get(key) != status.get(key) for key in ("cell", "band", "dut")):
            raise DeviceError("CMW500 小区或手机与既有证据不匹配")
        self.db.evidence(self.run, lte=self._device(self.lte, "capture_evidence"))
        self.notify("LTE", status)

    def _phone_ready(self, status, allow_idle_run=False):
        if status.get("local_stop") is True:
            raise UserStop("PHONE_USER_STOP")
        if status.get("ready") is not True:
            raise DeviceError("手机 GNSS/定位权限不可用")
        if not allow_idle_run and (status.get("active_run") != self.run
                                   or status.get("instance_id") != self.phone_instance):
            raise LinkError("手机服务已重启或运行 ID 改变")

    def _precheck(self, previous):
        config = self.config
        self._state("PRECHECK")
        self._check_stop()
        self._device(self.sim, "connect")
        identity = self._device(self.sim, "identify")
        if not config.mock and (identity.get("model") != "GSS7000"
                                or identity.get("software") != "SimREPLAYplus"
                                or not str(identity.get("version") or "").strip()):
            raise DeviceError("GSS7000 / SimREPLAYplus 版本或型号未确认")
        if not config.mock:
            low, high = identity.get("min_power_dbm"), identity.get("max_power_dbm")
            final = max(config.min_power_dbm, START_DBM - config.max_levels + 1)
            if (type(low) not in (float, int) or type(high) not in (float, int)
                    or not isfinite(low) or not isfinite(high) or not low <= final <= START_DBM <= high):
                raise DeviceError("计划功率超出现场确认的 SimREPLAYplus 设定范围")
        scenario = self._device(self.sim, "verify_scenario", config)
        required = {"scenario_id": config.scenario_id, "scenario_hash": config.scenario_hash,
                    "reference": config.reference, "static": True, "signals": config.scenario_signals,
                    "calibration_ref": config.calibration_ref, "power_definition": config.power_definition}
        if any(scenario.get(key) != value for key, value in required.items()):
            raise DeviceError("场景、静态真值、信号或校准未确认")
        if previous["evidence"].get("rf_safe") is False:
            self.sim_owned = True
        self._check_stop()
        self._device(self.lte, "connect")
        self._lte()
        self._check_stop()
        self.link_touched = True
        self._link("connect")
        phone = self.phone.command("HELLO")
        old_phone = previous["evidence"].get("phone", {})
        if old_phone and old_phone.get("device_id") != phone.get("device_id"):
            raise DeviceError("恢复所选手机与原运行不同")
        if not config.mock and not phone.get("device_id"):
            raise DeviceError("手机无法提供用于恢复核验的安装标识")
        active = phone.get("active_attempt")
        recoverable = {attempt["id"] for level in self.db.levels(self.run)
                       for attempt in self.db.attempts(level["id"]) if attempt["status"] in ("OPEN", "INVALID")}
        if active is not None and (phone.get("active_run") != self.run or active not in recoverable):
            raise DeviceError("手机正在运行无法归属本次记录的试验")
        self.phone_owned = phone.get("active_run") == self.run
        if self.phone_owned:
            self.phone.command("STOP_RUN")
        self._replay()
        self._phone_ready(phone | {"local_stop": False}, allow_idle_run=True)
        self.phone_instance = phone.get("instance_id")
        self.db.evidence(self.run, simulator=identity, scenario=scenario, phone=phone,
                         software_versions={"host": __version__, "protocol": 1,
                                            "app": phone.get("app_version")})
        self.notify("PHONE", phone)

        self._check_stop()
        if previous["status"] != "IDLE":
            self._verify_restore(previous)
        else:
            self.db.invalidate_open(self.run, "HOST_INTERRUPTED")
        self._check_stop()
        self.phone_owned = True
        self.phone.command("CONFIGURE_RUN", payload={"startup_mode": config.startup_mode})
        self.sim_owned = True
        self.db.evidence(self.run, rf_safe=False)
        if self._device(self.sim, "start").get("running") is not True:
            raise DeviceError("SimREPLAYplus 场景未运行")
        self._state("SCENARIO_READY")

    def _verify_restore(self, previous):
        status = self._device(self.sim, "get_state")
        if status.get("scenario_hash") != self.config.scenario_hash or type(status.get("running")) is not bool:
            raise DeviceError("恢复时场景或 RF 状态无法核验")
        levels = self.db.levels(self.run)
        last = levels[-1] if levels else None
        if status["running"]:
            self.sim_owned = True
            if last is None:
                raise DeviceError("恢复时运行功率没有检查点")
            verified_readback(status.get("power_dbm"), last["power_dbm"], self.config.power_tolerance_db)
        elif not self.config.mock and status.get("rf_off") is not True:
            raise DeviceError("恢复前须核验并记录 GNSS RF 已安全关闭")
        self.db.invalidate_open(self.run, "HOST_INTERRUPTED")

    def _replay(self):
        list(self.phone.drain())
        cursor = self.db.cursor(self.run)
        if cursor:
            self.phone.command("ACK", payload={"seq": cursor})

    def _check_attempt_link(self, attempt):
        status = self.phone.command("PING")
        self._phone_ready(status)
        if status.get("active_attempt") not in (None, attempt):
            raise LinkError("手机当前试验 ID 与 Windows 不一致")
        return status

    def _attempt(self, attempt, power):
        self._state("ATTEMPT_PREPARE")
        self._check_stop()
        if self.config.mock:
            evidence = "synthetic startup"
        else:
            evidence = self.prepare(attempt, self.config.startup_mode)
        self._check_stop()
        self.phone.command("PREPARE_ATTEMPT", attempt, {"startup_mode": self.config.startup_mode,
                                                        "preparation_evidence": evidence})
        self._check_stop()
        self._state("ATTEMPT_RUNNING")
        self._check_stop()
        args = {"power_dbm": power, "reference": self.config.reference,
                "observation_s": self.config.observation_s,
                "satellite_tolerance_ms": self.config.satellite_tolerance_ms}
        self.phone.command("START_ATTEMPT", attempt, args)
        deadline = monotonic() + self.config.observation_s + self.config.satellite_tolerance_ms / 1000 + 5
        while monotonic() < deadline:
            self._check_stop()
            events = list(self.phone.drain(check=self._check_stop))
            self._check_attempt_link(attempt)
            results = [event for event in events
                       if event["attempt_id"] == attempt and event["type"] == "ATTEMPT_RESULT"]
            if len(results) > 1:
                raise LinkError("同一试验收到多个最终结果")
            if results:
                self._state("ATTEMPT_EVALUATE")
                self._lte()
                self._check_stop()
                # Read back actual scenario and level after observing the phone.
                current = self._device(self.sim, "get_state")
                if current.get("running") is not True or current.get("scenario_hash") != self.config.scenario_hash:
                    raise DeviceError("试验期间 GNSS 场景状态无法确认")
                verified_readback(current.get("power_dbm"), power, self.config.power_tolerance_db)
                self._check_attempt_link(attempt)
                self._check_stop()
                return evaluate(self.config, results[0]["payload"])
            self.stop.wait(0.2)
        raise LinkError("采集窗口结束后仍未收到手机结果")

    def _recover_phone(self, attempt, reconnect):
        if reconnect:
            self._link("reconnect")
        current = self.phone.command("GET_STATUS")
        if current.get("active_run") == self.run:
            self.phone.command("STOP_ATTEMPT", attempt)
        self._replay()
        current = self.phone.command("GET_STATUS")
        if current.get("active_attempt") is not None:
            raise DeviceError("补传后手机试验仍活动")
        self._phone_ready(current)

    def _run_levels(self):
        for index in range(self.config.max_levels):
            power = START_DBM - index
            if power < self.config.min_power_dbm:
                break
            self._check_stop()
            level = self.db.level(self.run, power)
            if level["status"] == "FAIL":
                return self._fail_reason(power)
            if level["status"] == "PASS":
                continue
            self._state("LEVEL_SETUP")
            setpoint = self._device(self.sim, "set_power", power)
            verified_readback(setpoint.get("set_power_dbm"), power, self.config.power_tolerance_db)
            self._settle()
            reading = self._device(self.sim, "read_power")
            readback = verified_readback(reading.get("readback_dbm"), power, self.config.power_tolerance_db)
            self.db.readback(level["id"], readback)
            self.notify("POWER", {"power_dbm": power, "readback_dbm": readback})
            attempts = self.db.attempts(level["id"])
            valid = sum(row["status"] in ("PASS", "FAIL") for row in attempts)
            passed = sum(row["status"] == "PASS" for row in attempts)
            invalid = 0
            last_error = None
            while valid < SAMPLES:
                self._check_stop()
                attempt = self.db.create_attempt(level["id"])
                last_error = None
                try:
                    result = self._attempt(attempt, power)
                    self._check_stop()
                except UserStop as exc:
                    stopped = {"status": "INVALID", "reason": str(exc)}
                    self.db.decision(attempt, stopped)
                    self.notify("ATTEMPT", {"attempt_id": attempt, "power_dbm": power, **stopped})
                    raise
                except DeviceError as exc:
                    last_error = exc
                    result = {"status": "INVALID", "reason": str(exc)}
                self.db.decision(attempt, result)
                self.notify("ATTEMPT", {"attempt_id": attempt, "power_dbm": power, **result})
                if isinstance(last_error, LinkError) and not self.config.mock:
                    raise last_error
                if result["status"] == "INVALID":
                    invalid += 1
                    self._check_stop()
                    if invalid > INVALID_RETRIES:
                        raise DeviceError(f"INVALID 重试超限: {result['reason']}")
                    if last_error:
                        self._recover_phone(attempt, reconnect=isinstance(last_error, LinkError))
                        self._lte()
                else:
                    invalid = 0
                    valid += 1
                    passed += result["status"] == "PASS"
            self._state("LEVEL_EVALUATE")
            self.db.close_level(self.run, level["id"], power, passed >= PASS_COUNT)
            if passed < PASS_COUNT:
                return self._fail_reason(power)
        if START_DBM - (self.config.max_levels - 1) <= self.config.min_power_dbm:
            return "MIN_POWER_REACHED"
        return "MAX_LEVELS_REACHED"

    @staticmethod
    def _fail_reason(power):
        return "NOT_PASSED_AT_START" if power == START_DBM else "LEVEL_FAILED"

    def _shutdown(self):
        issues = []
        if self.phone_owned:
            try:
                try:
                    self.phone.command("STOP_RUN")
                except LinkError:
                    if not self.config.mock:
                        raise
                    self._link("reconnect")
                    self.phone.command("STOP_RUN")
                if self.phone.command("GET_STATUS").get("active_attempt") is not None:
                    raise DeviceError("无法确认手机已经停止")
                self._replay()
            except Exception as exc:
                issues.append(f"手机停止或日志补传失败 ({exc})")
        if self.link_touched:
            try:
                self._link("disconnect")
            except Exception as exc:
                issues.append(f"手机断开失败 ({exc})")
        if self.sim_owned:
            try:
                result = self._device(self.sim, "safe_stop")
                if result.get("rf_off") is not True or result.get("running") is not False:
                    raise DeviceError("GNSS RF 停止未确认")
                self.db.evidence(self.run, rf_safe=True)
            except Exception as exc:
                issues.append(f"GNSS RF 停止失败 ({exc})")
        return issues

    def execute(self, resume=False):
        with self.db.claim():
            previous = self.db.run(self.run)
            if previous["status"] == "FINISHED" or (not resume and previous["status"] != "IDLE"):
                raise ValueError("只能继续未完成的运行")
            state, reason = "PAUSED", "HOST_ERROR"
            try:
                self._precheck(previous)
                reason = self._run_levels()
                self._check_stop()
                state = "FINISHED"
            except UserStop as exc:
                state, reason = "STOPPED", str(exc)
            except DeviceError as exc:
                reason = str(exc)
            finally:
                try:
                    self._state("STOPPING", reason)
                    self.db.invalidate_open(self.run, reason)
                finally:
                    issues = self._shutdown()
                if issues:
                    state, reason = "PAUSED", f"{reason} | " + " | ".join(issues)
                self._state(state, reason)
            return self.db.run(self.run)
