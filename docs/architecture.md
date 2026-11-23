# 架构设计

## 物理链路
```text
                       +--------------------------+
                       | Windows / PySide6        |
                       | Orchestrator + SQLite    |
                       +------------+-------------+
                       LAN          |         LAN
                +-------+           |          +------+
                v                   |                 v
         GSS7000 / SimREPLAYplus    |             CMW500 / LTE
                | GNSS RF           | USB ADB         | LTE RF
                +------------+      |      +----------+
                             v      v      v
                          [ RF 屏蔽箱 ]
                          [ Root Android ]
```
两路 RF 应通过各自合规的滤波/耦合路径；严禁未经评估直接合路或开放辐射。

## 代码结构
```text
desktop/
  app/              # PySide6 UI，禁止业务判定放入控件
  core/             # 状态机、规则、配置、时间和错误模型
  instruments/      # GSS7000 / CMW500 / Mock 驱动
  transports/       # PhoneTransport, AdbTransport, LteTcpTransport(二期)
  storage/          # SQLite、迁移、事件日志
  reports/          # CSV JSON HTML
android/
  app/              # Kotlin GNSS 前台服务、Root 策略、Socket 服务
protocol/           # 版本化 JSON Schema + 示例
tests/              # Mock、集成、故障注入
docs/               # 文档
.github/workflows/   # CI
```

## 模块契约
- SimulatorAdapter: connect, load_or_verify_scenario, start, set_power, read_power, get_state, safe_stop。
- CellularAdapter: connect, verify_lte_environment, capture_evidence；不要求一期通过 CMW500 传定位数据。
- PhoneTransport: connect, send_command, receive_event, reconnect, disconnect；协议独立于 USB/LTE。
- GnssCollector: prepare, start_attempt, stop_attempt, location_event, satellite_event, persist。
- TestEngine: 单一状态机；UI 仅订阅事件；存储先于上报确认。
- 每个测试 run/level/attempt 有不可复用 ID，控制命令幂等；同一时间只有一个活跃 attempt。

## 状态
IDLE → PRECHECK → SCENARIO_READY → LEVEL_SETUP → ATTEMPT_PREPARE → ATTEMPT_RUNNING → ATTEMPT_EVALUATE → LEVEL_EVALUATE → (LEVEL_SETUP | FINISHED)；任何阶段可 STOPPING → STOPPED；异常进入 PAUSED/ERROR 并记录原因。恢复时先核验设备实际状态、功率、LTE 连接和 attempt 完整性；不盲目继续。

## 设计约束
真实驱动必须由明确证据解锁；Mock 模式界面显著标识。每次设备命令记录请求、响应、耗时和设备时间。同步使用单调时间测 TTFF，UTC 时间用于跨设备审计，不能直接相减计算 TTFF。
