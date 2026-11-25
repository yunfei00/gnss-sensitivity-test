# Android 独立采集与自动化测试验收方案

## 1. 目标与验收顺序

适用分支：fix/android-standalone-collector。先 CI，再无仪表手机验证，再 GSS7000 正式测试回归，最后按需 CMW500 A-GPS 回归。不得用模拟器结果代替射频验收。每个用例记录 APK commit、机型、Android 版本、SIM、网络、场景、操作时间、实际结果、PASS/FAIL/BLOCKED、截图和日志。未执行不得标 PASS。

## 2. 环境准备

- Windows 上位机、ADB、至少一台可正常定位的 Android 手机；建议另选一台无 SIM 手机。
- 下载与待验收 commit 一致的 CI android-debug APK；保留旧 APK 和测试数据库备份。
- 精确定位权限、系统定位开启；无 SIM 与无网络是不同条件，分别记录 Wi-Fi、蜂窝、飞行模式。
- 室外开阔环境或 GSS7000 屏蔽环境；不要在无有效卫星信号的室内以未定位判定软件失败。
- 正式冷热启动沿用原有准备流程，手动采集可能改变接收机状态，必须重新准备。
- 记录模拟器参考经纬度、功率、星座、场景时间和仪表配置；误差与手机估计精度不得混用。

## 3. 安装与自动化验证

```powershell
adb devices -l
adb install -r .\app-debug.apk
adb shell am start -n org.gnss.sensitivity/.MainActivity
adb shell dumpsys package org.gnss.sensitivity
adb shell dumpsys location
adb logcat -d -s AndroidRuntime
```

在仓库根目录执行（需 JDK17、Gradle 8.9、Android SDK35）：

```powershell
uv sync --locked
uv run --locked pytest -q
uv run --locked python -m desktop --mock --output results/ci
gradle -p android --no-daemon testDebugUnitTest lintDebug assembleDebug
gradle -p android --no-daemon connectedDebugAndroidTest
```

最后一条需已连接的测试设备或模拟器，建议专用模拟器，避免干扰现场手机。CI 三个 job（windows-python、android、android-integration）均需成功；检查测试报告无失败、APK 可安装。若 CI 尚未通过，不进入发布验收。

## 4. 手机独立采集测试（无需上位机）

| ID | 前置条件与步骤 | 预期结果 |
|---|---|---|
| M01 | 全新启动 APP，不点击任何采集按钮；检查 dumpsys location 中本应用请求 | 默认独立模式，无主动 GPS 请求 |
| M02 | 拔 USB，关闭上位机；点击开始采集 | 进入独立采集中，不等待 USB |
| M03 | M02 在有效卫星环境等待首次定位 | 显示卫星、C/N₀、首次 TTFF、经纬度、估计精度；不出现正式 PASS/FAIL |
| M04 | 首次定位后继续采集 60 秒 | 新定位条数继续增加；首次 TTFF 保持不变；卫星实时刷新 |
| M05 | 有超过 6 个卫星信号时查看列表 | 全部信号显示，按 C/N₀ 降序，参与解算标记及去重颗数合理 |
| M06 | 点击停止采集，检查 dumpsys location | 独立会话结束，本应用 GPS 请求释放；不再写入该会话遥测 |
| M07 | 连续开始/停止 10 次 | 无崩溃、重复会话或残留请求；每次新 UUID 和新 TTFF |
| M08 | 停止后重新开始 | 不使用上一轮经纬度或 TTFF 作为新定位 |
| M09 | 无 SIM，Wi-Fi 关闭，重复 M02–M06 | 能启动 GPS 采集；有有效卫星条件时可独立定位；不要求与联网 TTFF 相同 |
| M10 | 撤销精确定位权限后启动 | 提示授权，不崩溃，不错误显示正在采集 |
| M11 | 关闭系统定位后启动 | 提示开启定位，不创建有效采集会话 |
| M12 | 采集中关闭系统定位 | 会话停止或明确报错，释放请求，不显示虚假新定位 |
| M13 | 采集中插拔 USB、连接/断开上位机 | 独立采集不因 USB 断开停止 |
| M14 | 采集中切换后台 60 秒再返回 | 前台服务继续运行；返回后状态一致 |
| M15 | 采集中旋转屏幕或重建 Activity | 不创建第二个采集会话；状态正确恢复 |
| M16 | 采集中从通知栏停止 | 采集停止、GPS 请求释放 |
| M17 | 无有效卫星信号时开始，等待 60 秒 | 无虚假定位或 TTFF；允许继续等待及手动停止 |
| M18 | 采集中强制停止 APP，再重新打开 | 不自动恢复 GPS；已提交日志保留；异常结束会话可能无 SESSION_STOP |
| M19 | 采集中尝试切换自动化模式 | 模式切换被禁止，必须先停止 |
| M20 | 独立采集连续运行 30 分钟 | 无崩溃或明显 UI 卡顿；记录持续增长，记录文件大小及资源占用 |

## 5. 自动化模式与互斥回归

| ID | 操作 | 预期结果 |
|---|---|---|
| A01 | 切换自动化模式，启动 USB 通信，不连接上位机 | 等待连接，不主动请求 GPS |
| A02 | ADB forward tcp:18765 tcp:18765，连接上位机 | HELLO/GET_STATUS 正常；仅连接不触发定位 |
| A03 | CONFIGURE_RUN、PREPARE_ATTEMPT，不发送 START_ATTEMPT | 无 GPS 请求；显示等待开始 |
| A04 | START_ATTEMPT | 仅此时开始正式定位；保留原有 TTFF、首次定位和卫星关联逻辑 |
| A05 | 正式试验进行中尝试独立采集 | 拒绝，不并发占用接收机 |
| A06 | 独立采集中由上位机尝试 CONFIGURE_RUN | 拒绝，不打断手动采集，不创建正式试验 |
| A07 | 正式试验期间断开 USB | 正式试验按原协议标记 INVALID/TRANSPORT_ERROR，释放请求 |
| A08 | 正式试验期间点击结束自动化测试 | 当前试验停止，释放请求；允许后续切换独立模式 |
| A09 | 正常 STOP_RUN 后切换独立模式 | 可以重新启动独立采集，无残留 run 锁 |
| A10 | 独立停止后切换正式模式，重新执行准备 | 无手动日志混入正式报告；正式 TTFF 从本轮 START_ATTEMPT 计算 |
| A11 | 重复相同 command ID、FETCH_EVENTS、ACK | 原有幂等和游标行为不变 |
| A12 | 正式试验完成后切换独立模式但未开始 | 不显示正式试验的旧坐标、TTFF 或卫星列表 |
| A13 | 独立模式停止后重新启动正式试验 | 不自动使用手动定位结果；重新准备并采集 |
| A14 | 正式试验超时、停止、成功各执行一次 | 回调及 GPS 请求均释放，原有结果语义不变 |

## 6. 日志与数据库验收

调试 APK 可通过 run-as 导出数据库。先正常停止服务并确认无写入；如存在 WAL/SHM 文件应同时复制，不能只复制主文件后宣称数据完整。以下在 Windows cmd.exe 中执行，避免旧 PowerShell 二进制重定向损坏：

```bat
adb shell am force-stop org.gnss.sensitivity
adb shell run-as org.gnss.sensitivity ls -l databases
adb exec-out run-as org.gnss.sensitivity cat databases/gnss-events.db > gnss-events.db
```

若存在 gnss-events.db-wal 或 gnss-events.db-shm，使用同样命令分别导出到同目录同名文件。使用 SQLite 工具执行：

```sql
PRAGMA integrity_check;
PRAGMA user_version;
SELECT kind, COUNT(*) FROM manual_events GROUP BY kind;
SELECT session, kind, wall_ms, monotonic_ns, body FROM manual_events ORDER BY seq;
SELECT session, SUM(kind='SESSION_START') AS starts,
       SUM(kind='SESSION_STOP') AS stops FROM manual_events GROUP BY session;
SELECT run, COUNT(*) FROM events GROUP BY run;
```

| ID | 操作 | 预期结果 |
|---|---|---|
| D01 | 旧 APK 产生正式日志，备份后 adb install -r 新 APK | 数据库版本 2，原 events、commands、cursors 数据保留 |
| D02 | 正常独立采集并停止 | 每会话一个 START、一个 STOP，卫星及有效定位事件按序持久化 |
| D03 | 重启 APP 后导出 | 已提交记录保留，integrity_check 为 ok |
| D04 | 独立采集前后对比正式 events 记录数量（不运行正式试验） | 正式记录数量不变 |
| D05 | 正式采集后通过 FETCH_EVENTS 查询 | 不返回 manual_events 数据 |
| D06 | 强制停止或进程异常退出 | 已提交数据保留；无 STOP 的会话不得视为正常结束 |
| D07 | 检查 LOCATION_UPDATE JSON | latitude、longitude、location_elapsed_ns、accuracy_m、ttff_s、fix_count 正确；同一会话 TTFF 固定 |
| D08 | 检查 SATELLITE_STATUS JSON | constellation、svid、cn0_db_hz、used_in_fix 完整 |
| D09 | 检查系统时间和单调时间 | 同一会话单调时间非递减；系统时间变化不影响 TTFF |

## 7. GSS7000 与 CMW500 现场回归

参考 gss7000-static-scenario.md、stage-2-gss7000-validation.md、stage-3-cmw500-validation.md、stage-5-sensitivity-validation.md。功率、观察窗口、误差门限和冷热启动准备使用已批准的正式测试规范，不自行修改。

| ID | 操作 | 预期结果 |
|---|---|---|
| R01 | GSS7000 静态强信号，独立模式采集 | 坐标与参考点一致到合理范围；精度仅为 Android 估计值 |
| R02 | 同一场景正式 HOT 测试，至少 10 轮 | 首次定位及卫星关联符合既有规则；重点检查 TTFF 小于卫星回调周期时不被系统性判 INVALID |
| R03 | WARM、COLD 各至少 10 轮，逐轮执行规定准备 | TTFF 和误差判定沿用正式规范；无手动状态污染 |
| R04 | 固定功率及灵敏度扫描 | 与旧版本相同条件对比结果、INVALID 原因、报告完整性 |
| R05 | 无信号或低于定位门限 | 按正式规范超时或失败，不伪造定位 |
| R06 | CMW500 LTE、测试 SIM、已验证辅助数据链路 | 执行 AGPS 正式回归；仅 LTE attach 不代表辅助数据已送达，需独立证据 |
| R07 | 手动采集后执行正式 COLD 准备再开始 | 有明确准备证据；不得把未清除辅助状态的结果标为冷启动 |

R06 若尚未建立 SUPL/LPP 等辅助链路，记录 BLOCKED，不将其算作 A-GPS 验收通过。10 轮是本次建议的工程回归样本量，不替代正式统计规范。

## 8. 验收记录与放行

| ID | commit / 机型 | 实际结果 | PASS/FAIL/BLOCKED | 证据路径 | 缺陷编号 |
|---|---|---|---|---|---|
| M01 | | | | | |

每条用例复制一行。保留 CI 链接、APK SHA256、ADB 日志、截图、数据库导出、上位机报告和仪表场景证据。定位数据属于敏感数据，仅在授权环境保存，不提交真实坐标到公开仓库。

放行门槛：三项 CI 全绿；M/A/D 必测用例通过；GSS7000 正式回归通过；无崩溃、并发采集、日志串流、虚假定位或系统性 INVALID。AGPS 未验证时不得宣称 AGPS 已验收。发现失败先修复、重新运行相关用例及全部 CI。本文仅定义验收步骤，不代表已经执行或通过。
