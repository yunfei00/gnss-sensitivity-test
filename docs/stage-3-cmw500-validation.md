# P3 CMW500 独立控制（首版）
参考 https://github.com/yunfei00/instrument-automation-platform/tree/main/instrument_profiles/rohde_schwarz/cmw500/commands 的 lte_radio_basic.json、lte_signaling.json 和基线 docs/baselines/CMW500_PLATFORM_VALIDATION.md。BASE 3.5.120 / LTE 3.5.50 为参考版本，指令 manual_verified 不等于现场通过。
使用 TCP SCPI socket，默认 5025 待现场确认；参考平台已验证 VISA，若目标仅支持 VXI-11/HiSLIP，需补充 VISA transport。每次操作独立连接，LF，超时 5s，检查错误队列，不自动重发。连接参数本地 INI 自动保存。RF 路由只读，禁止自动重置或改变安全配置。
| 编号 | 操作 | 验收 |
|---|---|---|
| P3-01 | 连接/仪表信息 | IDN、版本、选件返回，核对实际版本 |
| P3-02 | 读取全部配置 | 双工、Band、EARFCN、带宽、RS EPRE、路由与原厂一致 |
| P3-03 | 停止小区 | OFF |
| P3-04 | 分别设置双工、Band、EARFCN、带宽 | CELL OFF 时设置并读回；使用现场合法组合 |
| P3-05 | 设置 RS EPRE | 批准范围内调整并读回，再恢复；非总小区功率 |
| P3-06 | 启动小区 | ON，原厂确认 RF |
| P3-07 | 手机注册 | 原厂人工核对；远程注册查询尚缺依据 |
| P3-08 | LTE 连接 | 原厂人工核对；远程状态查询待补 |
| P3-09 | 停止小区 | OFF，核对 RF |
| P3-10 | 重复三轮 | 每轮启动、注册、停止 |
| P3-11 | 停止后断网再恢复 | 明确报错，不重发，恢复后查询 |
| P3-12 | 重启软件 | IP/端口恢复，日志 results/cmw-debug/commands.log |
所有项待实机验收。不得将 CELL ON 等同 UE 注册。正式测试引擎仍使用人工适配器。待补：注册/连接状态确切命令、VISA transport（如现场需要）、RF 路由设置与校准、版本差异、完整自动化验收。关闭软件不自动改变 RF 状态，退出前手动停止并核对。CI 必须全绿才可冻结。
