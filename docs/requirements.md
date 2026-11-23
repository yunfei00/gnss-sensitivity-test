# 需求基线与范围

## 目标
构建单仓库的 Windows PySide6 上位机、Android Kotlin Root 测试 APP、仪器适配器与报告系统。用户在 Windows 一键开始，自动完成 GNSS 灵敏度功率下探并生成可追溯报告。

## 一期必需
1. CMW500 LTE 主频小区真实运行，手机注册并维持预期 LTE 状态；一期可人工配置小区，至少支持记录人工确认及证据；远程状态查询只有接口验证后才启用。
2. GSS7000 运行 **SimREPLAYplus** 静态场景；确认参考 WGS84 坐标、星座、信号频段、运行状态、功率和校准信息。
3. Root Android APP 采集 GPS_PROVIDER 经纬度、GNSS 状态、参与解算卫星数、C/N0、首次定位 TTFF；本地持久化原始事件。
4. Windows 通过屏蔽箱 USB 滤波接口、ADB 端口转发与手机双向通信；实时状态、开始/停止、断线重连和补传。
5. 自动执行每档 20 次有效试验、19/20 判定、1 dB 下探、停止/恢复、SQLite 与 CSV/JSON/HTML 报告。
6. 提供 Mock 仪器和模拟手机，支持不连接设备的完整闭环回归；硬件测试单独验收。

## 二期范围
- 增加 LteTcpTransport 替换 AdbTransport；CMW500 LTE IP 承载及到 Windows 的数据路由需要实机验证。
- GNSS 采集、状态机、消息协议、存储和报告不变；开展 USB 与 LTE 两种连接方式的干扰对照。

## 不在一期范围
- 不使用 CMW500 直接读取 Android GNSS 内部数据。
- 不把 SimTEST 或 SCU 命令当作 SimREPLAYplus 命令。
- 不承诺 Root 能对所有芯片执行真正冷启动；必须验证启动状态。
- 不自动配置未知 CMW500 LTE 选件或未核实的 SimREPLAYplus 远程命令。

## 待现场确认（阻塞真实自动化）
SimREPLAYplus 版本、远程控制文档 DGP01449AAA、可用命令及功率读回；CMW500 型号/固件/选件与 LTE 连接证据；手机 Android 版本/芯片/Root 实现；GNSS 场景坐标与功率定义；屏蔽箱 USB 过滤能力、RF 连接和线损；GNSS cold/warm/hot/A-GPS 目标启动模式；每次试验间复位方式、场景是否连续及辅助数据策略。
