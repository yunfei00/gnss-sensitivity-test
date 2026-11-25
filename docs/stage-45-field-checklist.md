# 一期 GNSS 基线：P4 / P5 现场操作卡

**逐项测试用例与现场签收表**：[`p1-p5-field-acceptance-cases.md`](p1-p5-field-acceptance-cases.md)。请按 P1→P2→P3→P4→P5 顺序执行，共 78 条；逐项记录实际结果和证据。

## 启动
1. 在 Windows 上位机更新 `codex/phase-1` 分支，按现有项目依赖运行 `uv run python -m desktop`。
2. 确保 GSS7000 独立调试页通信正常。**GNSS_ONLY 无需 CMW500、NAS 或 RRC**；仅 GNSS_LTE 联合模式才要求 P3。
3. Android APP 打开、授权精确定位，点击 **启动 USB 采集**；在上位机选中唯一 USB 设备。GSS7000 已连接 GNSS 屏蔽箱；确认没有对外辐射。
4. 打开 **P4 / P5 联合测试**，选择默认 GNSS 独立模式，输入 GSS IP/端口、仪表场景完整路径、场景真实 WGS84 纬经度。
5. 输入校准数据：某个真实测量输出功率 dBm、对应 `POW_LEV` 参考 dB、校准有效上下限、校准证据编号、DUT 参考平面。校准范围必须覆盖计划扫描的所有档位，并确认范围内功率调节斜率 1 dB/dB。**仅单点测量不足以证明整个范围有效**。

## P4 验收
点击 **开始 P4 固定 20 次**。程序仅预检 GSS/手机，不访问 CMW、不等待 LTE RRC；GSS 加载并运行场景，设置经校准的 -120 dBm。弹窗要求独立 RF 功率核验证据编号；输入后自动运行 20 次 HOT GNSS 采集，每轮手机 PING 检查 ready 和无活动试验，Android 重新启动 GPS_PROVIDER 并记录新的单调计时起点。每轮前后检查 GSS 状态。结束后查看 **打开本次报告**。

验收重点：20 条有效试验；TTFF ≤20.3s、水平误差 ≤101.3m、used_in_fix ≥4 为 PASS；至少 19 PASS 为 P4 通过。INVALID 不计入 20 条有效数；连续 INVALID 超限暂停；仪器/USB 异常不能记为 GNSS FAIL。

## P5 验收
输入最低功率（例如 -122 dBm）和最大档数（例如 3），点击 **开始 P5 逐档扫描**。依次测试 -120、-121、-122 dBm，每档 20 次有效试验，首次失败停止；最后通过档作为阈值。每档独立加载/停止仪表并记录校准证据。若首档不通过，阈值为“无”，不能填 -120 dBm。

## 输出和故障
结果目录为 `results/stage45/<UUID>/`，包含 `fixed.json` 或 `sweep.json`、`level_-120.json` 等档位文件、`phone_audit_*.sqlite`、`report.csv`、`report.html`。命令日志 `results/stage45/commands.log`。

- 断开手机 USB：当前轮无效/暂停，按安全停止处理；不生成虚假灵敏度。
- GSS 通信异常或外部功率核验失败：暂停，检查仪表 RF 实际状态，禁止自动盲重发功率命令。
- CMW RRC 断开：仅 GNSS_LTE 模式检查；GNSS_ONLY 不检查。
- 点击 **取消并安全停止**：程序请求手机 STOP_RUN、GSS 停止复位。GNSS_ONLY 不操作 CMW；GNSS_LTE 模式仅关闭本次程序自己开启的 CMW 小区。若 CMW 小区原本已 ON，程序不会擅自关闭；操作员须自行核对最终 RF 状态。
- 本次仅实现 HOT 自动化。COLD/WARM/AGPS 需要独立机型级状态准备，**不可用 HOT 结果冒充**。

## 判定边界
这是待实机验证的代码，不是已完成现场验收的声明。尤其 GSS V6 不支持 SIG_LEVEL 功率远程读回，校准 dBm 必须通过外部证据确认。现场遇到仪表指令差异，以实机日志为准修改版本适配，不要修改阈值来掩盖故障。
