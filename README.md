# GNSS Sensitivity Test

Windows + Root Android + Spirent GSS7000 (SimREPLAYplus) + R&S CMW500 自动化 GNSS 接收灵敏度测试系统。

## 项目阶段
- **一期 v1.0**：CMW500 建立 LTE 主频测试小区，GSS7000 提供静态 GNSS 场景；Windows 通过屏蔽箱 USB 滤波穿墙接口与手机 ADB 通信，实现完整自动化闭环。
- **二期 v2.0**：保留两台仪器和全部测试算法，仅将手机数据通道替换为 CMW500 LTE 用户面 IP/TCP 通道；需现场验证 CMW500 选件和路由能力。
- **重要**：一期 USB 是工程过渡方案，灵敏度正式结论必须评估 USB 影响；LTE 自身也可能影响 GNSS，二期同样需对照验证。

## 设备与连接
Windows —LAN→ GSS7000/SimREPLAYplus；Windows —LAN→ CMW500（如有远控）；Windows —USB→ 屏蔽箱滤波穿墙接口 → Root Android 手机。GSS7000 GNSS RF 与 CMW500 LTE RF 分别经合规射频路径进入屏蔽箱。CMW500 **一期即参与 LTE 网络环境**，但一期定位数据不通过 CMW500 上传。

## 默认测试规则
- 初始功率 **-120 dBm**，每通过一档降低 **1 dB**；功率定义、校准平面、线损和硬件范围必须现场确认。
- 每档 **20 次有效试验**，成功数 **≥19** 判 PASS；不满足则停止，下探前最后通过档为灵敏度阈值。初始档不通过则报告“未在起始档通过”，不可编造阈值。
- 单次 PASS：TTFF ≤ **20.3 s**、首次有效定位水平误差 ≤ **101.3 m**、参与解算卫星数 ≥ **4**；必须有新鲜 GPS_PROVIDER GNSS fix。
- 设备控制失败、缺少可靠卫星数、断链等标记 **INVALID**，不算 GNSS FAIL，不占 20 次有效样本；有限重试，超限安全停止。
- 首次 fix 与卫星状态必须按单调时间戳关联；不能将 Android reported accuracy 当作与参考坐标的实际误差。
- 观测超时建议初值 **30 s**（可配置），晚于 20.3 s 的 fix 仍判 TTFF FAIL。

## 文档导航
- [P0–P5 安装、运行、报告和现场交接](docs/phase-one.md)
- [需求与范围](docs/requirements.md)
- [系统架构](docs/architecture.md)
- [设备连接与安全](docs/hardware.md)
- [测试算法与状态机](docs/test-procedure.md)
- [Android 采集规范](docs/android.md)
- [通信协议](docs/protocol.md)
- [仪器集成](docs/instruments.md)
- [数据、报告和验收](docs/acceptance.md)
- [开发计划](docs/development-plan.md)
- [Codex 开发约束](AGENTS.md)

## 开发原则
Mock 与真实仪器驱动分离；未经确认的 SimREPLAYplus/CMW500 命令不得伪造为已验证；默认模拟模式不能冒充真实硬件测试。公开仓库不得包含设备密码、真实客户数据、商业手册原文或内网信息。

## 无仪器快速验证

```powershell
uv sync --locked
uv run --locked pytest -q
uv run --locked python -m desktop --mock
uv run --locked python -m desktop
```

Mock 默认跑完 3 档并在 `results/mock` 写入 SQLite、CSV、JSON、HTML。真机流程通过 USB ADB 连手机，SimREPLAYplus 与 CMW500 状态通过现场操作和证据确认。

## USB 设备与 Android 调试 APK

现场模式从「ADB USB 设备」下拉框选择已授权、在线的 USB 手机。程序启动时扫描，后台每 10 秒刷新一次，并监听插拔事件。开始后锁定设备。当前手机掉线时，中断轮次记为 INVALID，重连后选择原手机和历史运行再点击「恢复选中运行」。

在 Windows 仓库根目录运行 `.\android\build-debug.ps1`，或在 [GitHub Actions](https://github.com/yunfei00/gnss-sensitivity-test/actions/workflows/ci.yml?query=branch%3Acodex%2Fphase-1) 选择成功运行，从 **Artifacts → android-debug** 下载 `app-debug.apk`。这是调试签名安装包。构建环境、ADB 版本和安装步骤见 [一期使用说明](docs/phase-one.md)。
