# 数据、报告与验收

## 数据模型
run(id, started_utc, scenario_id, scenario_hash, reference_lat, reference_lon, startup_mode, software_versions, connection_mode, lte_evidence, calibration_ref, mock_flag)
level(id, run_id, set_power_dbm, readback_dbm, valid_count, pass_count, status)
attempt(id, level_id, ordinal, t0_monotonic_ns, first_fix_monotonic_ns, ttff_s, lat, lon, error_m, used_in_fix, status, reason)
event(id, run_id, attempt_id, seq, source, event_type, timestamp_utc, monotonic_ns, payload)
device_log(id, device, request, response, duration_ms, outcome)
所有数据支持版本化迁移、断点恢复与审计；敏感数据本地保存，公开仓库只放合成示例。

## 报告
HTML（可读）、CSV（逐次）、JSON（完整结构）三种必需格式；Excel 可作为增强。报告应包含设备型号/软件版本、LTE 状态、GNSS 场景与参考坐标、功率定义/校准、USB/LTE 通信模式、20 次明细、19/20 判定、最后通过档、停止原因、INVALID 次数、日志路径、是否真实设备、未验证项及测试环境限制。

## CI 自动验收
1. Python 单元测试：20.3/101.3/4 的边界，18/20 与 19/20，-120/-121 dBm，初始失败、达到最低功率、设备故障、停止。
2. Android 构建与 Kotlin 测试：时间戳新鲜度、首次 fix 锁定、satellite 关联、重复命令和事件补传。
3. 协议契约测试：版本、schema、幂等、断线重连、序列号去重。
4. Mock 全链路：无硬件一键运行并输出报告；故障注入不误判 GNSS FAIL。
5. Windows PySide6 smoke test：启动、停止、设备状态、实时指标与历史结果。
6. ADB 发现与设备锁定：后台初次扫描和周期刷新，无设备禁用现场开始，单台自动选中，多台保留有效选择，过滤无线、unauthorized 和 offline，显示 ADB 超时。非当前设备插拔不干扰，当前设备掉线只将未完成轮次记为 INVALID，须手动恢复原手机。
7. Android CI 执行 `testDebugUnitTest`、`lintDebug`、`assembleDebug` 并上传 `android-debug`。Artifact 含 `app-debug.apk`，Windows 一键脚本见 [一期使用说明](phase-one.md)。

## 现场验收
- USB 穿墙口关箱后稳定连接，ADB/Root/APP 正常。
- 用 `adb -s SERIAL install -r` 安装调试 APK，实际验证精确定位授权、Android 前台采集服务和 USB TCP 18765 双向通信。
- 用两台真机检查型号显示、USB 调试授权、其他手机插拔、当前手机断开后的安全停止，以及原手机重连后手动恢复。
- CMW500 LTE 小区连接真实成功，有可追溯证据。
- GSS7000 SimREPLAYplus 场景/参考位置/功率变化得到实机验证。
- -120 dBm 20 次、19/20 判定及 -1 dB 自动下探完整跑通。
- 停止真正中断后续动作，恢复不重复计数。
- USB 与无 USB 或 LTE 方案做干扰对照，差异明确记录。
- CI 全绿并保留现场验收报告；不能以 Mock 通过代替真实仪器验收。
