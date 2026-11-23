# 仪器适配器与待验证接口

## GSS7000 / SimREPLAYplus
已知官方资料说明 SimREPLAYplus 支持选定的以太网远程控制功能，但**具体指令、端口、功率单位及读回能力必须以现场安装版本的用户手册 DGP01449AAA 和实机验证为准**。绝不能把 SimTEST、SimGEN 或 SCU 的命令直接移植为 SimREPLAYplus 的已验证接口。

建议在仪器 Windows 控制机检查：`D:\\posapp\\software\\<version>\\gui\\Docs`，记录软件版本、远控启用步骤、命令样例、功率绝对值/相对偏移、响应、错误码、最大最小范围。若某操作无法远控，提供显式“人工操作 + 人工确认”模式，不假装全自动。

适配器契约：connect / identify / verify_scenario / read_reference_position / start_or_verify_running / set_power / read_power / get_state / safe_stop。若无可验证读回，需使用替代证据并明确降低自动验收级别，禁止盲降功率。

## CMW500
一期作为真实 LTE 主频网络模拟设备，手机必须实际注册。支持手动配置并记录截图/日志证据；若现场确认远程查询命令、选件及固件后再实现 CellularAdapter。**一期不要求 CMW500 LTE 用户面 IP 数据通路。**

二期需要 LTE 注册、承载建立、IP 分配、到 Windows 的双向路由、稳定性和安全性验证，才能实现 LteTcpTransport。

## Mock
模拟器提供场景状态、功率下探、读回误差、超时、断线、功率设置失败；CMW 模拟 LTE 已注册/未注册；手机模拟 TTFF、误差、卫星数、INVALID 和中断。Mock 与真实模式的界面、日志、报告必须明确区分。

## 资料
- Spirent GSS7000 数据表： https://spirentfederal.com/wp-content/uploads/Spirent-Federal-MS7000-Issue-1-30-GSS7000-Series-GNSS-Constellation-Simulator-Datasheet-with-Product-Specification.pdf
- 官方手册编号：DGP01449AAA（需从授权安装目录获取；不要上传商业手册到公开仓库）。
