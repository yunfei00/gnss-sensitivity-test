# P4 / P5 联合验收（2026-11-24 开发版）

## 当前实现与入口
- `desktop/stage4_fixed.py`：单一经校准的固定输出功率，20 次**有效**独立试验，19/20 通过；逐次记录 TTFF、误差、参与解算卫星，INVALID 不算有效样本；超限暂停；取消及异常执行安全停止。
- `desktop/stage5_sweep.py`：从 -120 dBm 开始逐档 -1 dB；每档复用 P4 的 20 次测试；首个 FAIL 停止，记录最后一个 PASS 档。首次 -120 dBm FAIL 时阈值为空；达到最低功率或最大档数时正常结束。
- 输出 `sweep.json` 和 `level_-120.json` 等文件；不覆盖已有运行。每档独立预检/启动/停止，避免前一档残留状态被误当作当前档。
- `tests/test_stage4_fixed.py`、`tests/test_stage5_sweep.py`：无硬件合成适配器回归，仅用于软件逻辑，不代表现场通过。

## 三类设备接口（已提供实机适配器，待现场验收）
- CMW500：`preflight()`、`establish_lte()`、`rrc_connected()`、`safe_stop()`。**RRC CONN 不能替代 NAS 注册证据**，现场须核对 LTE 小区和真实 DUT。
- GSS7000：`preflight()`、`start_scenario(scenario_id)`、`set_power_dbm(dbm)`、`verify_power_dbm(dbm)`、`safe_stop()`。只有实际 RF 参考平面校准成立且确认后，`verify_power_dbm` 才允许返回 True。
- Android USB：`preflight()`、`prepare(startup_mode)`、`attempt(reference, observation_s)`、`stop_run()`。必须返回真实的 `ATTEMPT_RESULT` 原始遥测字段，不能返回自行构造的 PASS；必须沿用 JSONL 协议、消息 ID/ACK/重放校验。每轮 HOT/COLD/AGPS 准备证据必须真实。

## 仪表特别注意
SimREPLAYplus V6 的 `-,POW_LEV,v1_a1,...` 参数是**参考 dB**，不是绝对 RF 输出 dBm；`SIG_LEVEL` 在 V6 不支持。不能简单把 -120 dBm 填进 `POW_LEV`，也不能把“命令发送成功”或“记录的设定值”伪装成仪表实测读回。须由现场校准表/测量设备确认绝对功率、线损、参考平面与容差；缺证据时保持 PAUSED，不产生正式阈值。

## 明日现场验收顺序
1. 在 P2 页面验证 GSS7000 真实场景加载、启动、停止和相对功率变化，核对版本和外部校准记录。
2. 在 P3 页面验证 CMW500 LTE 小区、真实手机 NAS 注册及 RRC CONN，核对 RF 路由和线损。
3. 手机启动 USB 采集服务，核验新鲜首次定位、TTFF 和 used_in_fix；确认 20 次可重复执行。
4. 三设备联合固定功率 20 次；中途断开 USB、GSS 网络、CMW 网络，验证不计伪 FAIL 且停止安全。
5. P5 依次验证 -120/-121/-122 dBm；失败停止及阈值记录；再测首次 -120 失败、无效数据超限、用户取消、重复启动不覆盖历史记录。
6. 检查 JSON/数据库/HTML 报告与实机原始日志一致，确认 CI。

## P4/P5 实机入口（新增）
主界面 **P4 / P5 联合测试** 页现已接入 `Stage45Worker`、`CmwLteAdapter`、`GssCalibratedAdapter`、`UsbGnssAdapter`：
- 读取 GSS7000、CMW500 的本机 IP/端口配置，支持手动输入并自动保存 P4/P5 独立配置。
- 要求输入真实场景完整路径、WGS84 场景参考坐标、校准测得输出 dBm、与之对应的 POW_LEV 参考 dB、有效校准上下限、证据编号和输出参考平面。
- 软件在校准范围内按 1 dB 斜率换算 `POW_LEV` 参考值；**必须由现场验证整个范围内的 1 dB 线性响应**，不能用单点校准推断有效范围。
- P4 启动固定 -120 dBm，P5 使用最低功率/档数逐档运行；每档记录独立 JSON 和手机 SQLite 审计，支持停止；结束后导出 `report.csv` 和 `report.html`。
- 每档启动时 GSS 重新加载场景、启动并设置功率；每轮前后检查 GSS 运行状态和 LTE RRC，功率独立核验由操作员填写外部证据。
- 当前 USB 自动适配只实现 **HOT**；COLD/WARM/AGPS 不允许假装已准备，后续必须另做机型级启动控制。
- CMW 已开启的小区不会被自动关闭；仅对本程序主动开启的小区执行自动关闭。退出时需要人工确认现场 RF 安全状态。
- 连接/功率/手机失败后暂停，不把仪器异常误判为 GNSS FAIL。

## 开发状态
P4/P5 **真实仪表适配器、USB 采集适配器、GUI 一键入口、逐档判定和结果记录均已接入代码**。尚待 CI 最终通过与现场三设备联调；不能声称硬件验收通过。NAS 注册仍须人工核对，V6 绝对功率须外部校准证据，手机 HOT 需要每轮真实准备证据。
