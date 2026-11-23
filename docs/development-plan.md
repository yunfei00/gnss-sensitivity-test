# 开发计划 P0–P7

## P0 基础工程
建立 desktop/、android/、protocol/、tests/、CI、配置示例、日志与 Mock；文档基线和验收矩阵。验收：Windows Python 与 Android CI 可构建，Mock 初始运行成功。

## P1 Android GNSS
Kotlin GNSS Service、经纬度/误差/TTFF/卫星/CN0、首次 fix 规则、Root 启动模式诊断、本地持久化。验收：模拟与手机实际定位事件可区分，数据可追溯。

## P2 USB 双向通信
ADB forward + JSONL TCP、指令幂等、事件 ACK、断线补传、开始/停止/重连。验收：关闭屏蔽箱 USB 仍可稳定收发。

## P3 Windows 上位机
PySide6 设备面板、配置、实时数据显示、逐轮列表、状态机、停止、SQLite、报告。验收：Mock 端到端。

## P4 仪器集成
GSS7000 SimREPLAYplus 版本/命令/功率读回现场探针；CMW500 LTE 注册证据/状态；真实与 Mock 模式严格隔离。验收：现场证据确认后才标记驱动 VERIFIED；不支持的接口清楚提示人工步骤。

## P5 全流程
-120 dBm 开始、1 dB 下探、每档 20 有效试验、19 次 PASS、单次三个指标、INVALID 处理、停止恢复、报告。验收：自动化边界用例和 Mock 完整闭环。

## P6 一期现场验证
真实 USB+LTE 环境、GSS 场景、校准记录、全流程验收、USB 干扰 A/B、发布 v1.0；真实设备限制必须透明披露。

## P7 二期 LTE
验证 CMW500 用户面 IP、Windows 路由、认证/加密，新增 LteTcpTransport，复用原协议/状态机，USB/LTE A/B 对照，发布 v2.0。

## 开发节奏
每阶段：实现→单测→集成测试→CI 全绿→提交/PR→阶段验收。禁止仅凭单次模拟结果声称真实硬件通过。阻塞硬件信息时先完成 Mock 和接口契约，列出待现场执行的可复制诊断步骤，不臆造仪器命令。
