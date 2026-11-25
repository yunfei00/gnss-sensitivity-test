# P4 固定功率 20 次定位联合测试 — 开发与验收

## 范围
固定一个经现场校准的 GNSS RF 输出功率；CMW500 LTE RRC 连接、GSS7000 场景控制和 Android USB 原始定位采集共同构成测试闭环。不做自动降功率扫描（P5），不使用 LTE 代替 USB（P6）。

## 已落地
- `desktop/stage4_fixed.py`：可注入硬件适配器的 P4 调度内核，预检、LTE 建链、GNSS 场景及功率、20 个有效轮次、原始遥测判定、原子 JSON 记录、停止与故障暂停。
- `tests/test_stage4_fixed.py`：模拟适配器验证 20 轮完成、功率未确认禁止测试、INVALID 不计有效次数。模拟测试不能替代真机验收。
- 成功标准：20 次有效定位中至少 19 次通过；每轮 TTFF ≤20.3 秒、水平误差 ≤101.3 米、参与解算卫星 ≥4。INVALID 最多额外重试 2 次（连续）。

## 必须补齐后才能宣布 P4 可实机测试
1. **GSS7000 适配**：当前 V6 `POW_LEV` 为参考 dB，而 P4 输入为校准后的 dBm；必须提供真实校准转换和独立确认，禁止将两者直接等同。V6 没有功率读回时须明确外部仪表/原厂界面核验方式及证据。
2. **CMW500 适配**：把 `CmwSession` 的已验证 LTE 初始化、小区配置、RRC 查询及安全停止封装到 P4 接口；必须核实现场实际连接参数。
3. **Android USB 适配**：复用 `AdbTransport` 的消息关联、ACK、事件收集及 STOP_RUN；每轮 `PREPARE_ATTEMPT` 必须有真实启动状态证据，不能伪造 HOT/WARM/COLD。
4. **GUI**：增加 P4 页面及参数保存、运行进度、停止按钮、现场预检确认、报告入口。不要阻塞 UI 线程。
5. **验收**：CI 全绿，Windows 启动、三设备连通、断线/取消/超时安全停止，现场固定功率完整 20 轮与报告复核。P3 未完成的实机验证仍单独保留。

## 明日现场准备
连接 CMW500、GSS7000、Android USB；确认屏蔽环境、LTE RF 路由、校准参考、真实场景和经纬度；检查手机 APP 已启动采集服务。未完成上述适配之前，请分别在 P2/P3 调试页验证，不要把独立调试结果标为 P4 联合测试通过。

## 状态
**P4 调度内核已提交，硬件适配及 GUI 未完成；不可标记 P4 完成或通过实机验收。**

## 2026-11-24 P4/P5 实机集成更新
现已新增 `desktop/stage45_gui.py`、`stage45_instruments.py`、`stage45_phone.py`、`gss_calibration.py`，并在 Windows 主界面增加 P4/P5 联合测试页。CMW500 小区与 RRC、GSS7000 场景/功率、Android USB JSONL 原始采集已接入 P4/P5 调度。**本次仍未做现场仪表验收**，所有实机结果须明日验证。V6 功率要求外部校准证据，每轮 HOT 准备仍需现场确认；COLD/WARM/AGPS 未自动化。详见 `docs/stage-5-sensitivity-validation.md`。
