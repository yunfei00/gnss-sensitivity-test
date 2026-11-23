# P0–P5 使用说明与现场交接

## Windows 快速开始

在仓库根目录安装 Python 3.12 或 3.13 和 uv，然后运行：

```powershell
uv sync --locked
uv run --locked pytest -q
uv run --locked python -m desktop --mock --output results/mock
uv run --locked python -m desktop
```

命令行 Mock 默认依次运行 -120、-121、-122 dBm，前两档各通过 20 次，第三档 0/20，最后通过档为 -121 dBm。每次 CLI 运行请指定独立输出目录。Windows 界面默认选择 Mock，修改配置里的最低功率、最大档数和观察窗口后可直接开始。界面实时显示设备状态、定位和逐次判定。选中历史运行后可以查看结果、打开报告或恢复未完成运行。

### Windows 操作台

- **运行监控**显示当前功率、首次定位 TTFF、水平误差、解算卫星、有效样本计数和逐次判定。安全停止操作位于顶部。
- **测试配置**按功率与观察、场景与校准两组填写，字段标有单位。现场模式与 Mock 分别保留本次打开期间的配置草稿。现场操作和 RF 安全停止通过表单记录实际读值和证据。
- **历史与报告**显示状态、最后通过档和对应明细。选中运行后可打开 HTML 报告或结果目录，从报告中访问 CSV、JSON 与 SQLite。

### 选择 USB 手机

- 安装支持 USB 连接类型跟踪的 Android SDK Platform Tools（例如 37.0.1），以 `adb` 在 PATH 中可用。若本机有多个 ADB 版本，可在 `.env` 用 `GNSS_ADB` 指定 SDK 的 `adb.exe`。上位机连接本机 ADB 服务 `127.0.0.1:5037`。如果该服务仍由旧版 ADB 提供且提示 `unknown host service`，请在其他 ADB 会话结束后用已更新的 Platform Tools 重启该服务。
- 现场模式的下拉框显示序列号和可获取的型号。启动即后台扫描，每 10 秒重新获取完整列表，ADB 插拔和状态事件会提前刷新。单台自动选中，多台时保留有效选择或等待手动选择。无线 ADB、模拟器、offline 和 unauthorized 不可选。ADB 失败或超时会显示原因。
- 开始后锁定选中的序列号和本次 USB 连接。设备命令都使用 `adb -s SERIAL`。列表扫描与服务启动属于 ADB 主机操作。其他设备插拔不影响当前测试。
- 锁定手机掉线时暂停并确认 RF 安全停止，已完成结果保留，当前轮次记 INVALID。重连后选择原 USB 手机和历史运行，点击「恢复选中运行」。上位机核对原序列号及已有的手机安装标识，再补传日志并继续。

故障注入使用可重复的 `--fault` 或界面的逗号分隔输入。例如：

```powershell
uv run --locked python -m desktop --mock --output results/replay --fault disconnect --fault no_satellite
```

故障包括 `gss_connect`、`gss_set_power`、`gss_readback`、`gss_stop`、`lte_unregistered`、`phone_connect`、`phone_prepare`、`phone_health`、`no_satellite`、`disconnect`、`drop_ack`、`hold_attempt`、`late_fix`、`position_error`、`few_satellites` 和 `timeout`。同一故障可以输入多次。`hold_attempt` 可用于界面停止和恢复测试。

## Android 调试 APK 构建、下载与安装

准备 JDK 17（或兼容 JDK）、Gradle 8.9、Android SDK Platform 35、Build Tools 34.0.0 和 Platform Tools。设置 `JAVA_HOME`、`ANDROID_HOME`，并将 Gradle 和 ADB 加入 PATH。在仓库根目录运行：

```powershell
.\android\build-debug.ps1
```

脚本执行 `testDebugUnitTest`、`lintDebug` 和 `assembleDebug`，输出 `android/app/build/outputs/apk/debug/app-debug.apk`。Gradle 未加入 PATH 时可传入 `-Gradle` 和 `gradle.bat` 的完整路径。

也可以在 [GitHub Actions](https://github.com/yunfei00/gnss-sensitivity-test/actions/workflows/ci.yml?query=branch%3Acodex%2Fphase-1) 打开对应提交的成功运行，登录 GitHub 后在页底 **Artifacts** 下载 **android-debug**，解压得到 `app-debug.apk`。它使用调试签名。正式签名流程若配置，密钥和口令只通过 GitHub Secrets 注入。

```powershell
adb devices -l
adb -s SERIAL install -r .\android\app\build\outputs\apk\debug\app-debug.apk
# 如果使用 Actions 下载的文件，将 APK 路径改为解压后的位置。
```

`install -r` 覆盖安装要求手机上的旧包与新包使用同一签名。不同 CI 运行或不同 Windows 环境生成的调试签名可能不同。若 ADB 报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`，请保留或导出旧版记录后，再决定如何更换安装包。

APP 支持 Android API 26 及以上。关箱前打开 APP，在「采集监控」点击「启动 USB 采集」，授权精确定位并开启系统定位。连接、定位指标和卫星信号可在该页查看。Android 13 及以上可允许通知，以便查看前台采集状态和停止入口。「设备诊断」显示权限、系统定位和本机事件记录，可按现场需要执行 Root 检测。基础定位采集无需 Root。启动模式准备由操作者执行目标机型上已有证据的步骤，每轮填写经过验证的模式、命令、退出码、前后状态及本地证据引用。

上位机通过 ADB 给 Android 的 `127.0.0.1:18765` 分配动态的本机端口。多台手机时在下拉框选择 USB 序列号，并在关箱前确认调试授权。Android 先写 SQLite，再通过 JSONL 响应 FETCH。Windows 提交 SQLite 后 ACK。手机连接失效会取消当前采集，已记录事件在人工恢复时补传。结束时 Windows 核验采集已停并要求确认 GNSS RF 关闭。若停机确认失败，运行保留为 PAUSED，界面和报告记明原因。

## 现场模式

1. 按 [硬件规范](hardware.md) 核验 USB 滤波穿墙、两路 RF 路径、隔离和功率范围。
2. 在 CMW500 上建立预期 LTE 主频小区，核对当前 DUT 注册。按提示填型号、固件、选件、小区、频段、DUT 标识及证据引用。每次试验后核对观察窗口内的注册日志。
3. 选择现场模式，填写静态场景 ID、场景包哈希、WGS84 真值、星座与信号、功率定义、校准记录号、功率下限及最大档数。填写仪器允许的真实功率范围。
4. 依界面提示启动 SimREPLAYplus、设置功率、记录独立读回、准备手机启动状态。每次采集结束后核对场景持续运行与实际功率，再提交试验决策。真机现场流程按档位和轮次自动推进，仪器和启动方式通过人工证据确认。
5. 要恢复既有运行，先选中历史记录。恢复会核验场景、现场 RF 安全或正在运行的实际功率、LTE 小区、手机安装标识和活跃试验，然后补传并标记中断轮次。已经写入的有效样本会保留。无法核验时暂停排查。

## 判定与数据

- -120 dBm 起，每档满 20 次有效样本。19 次 PASS 后降 1 dB；首档不足 19 时阈值为空，后续任一档失败时记录最后通过档。
- TTFF 从 Android `elapsedRealtimeNanos` 的 t0 和首次 GPS fix 计算。水平误差由 WGS84 测地线逆解重算。APP 锁定第一次新鲜 GPS fix，丢弃 mock、过期和未来时间戳以及无效坐标。
- Android 以回调接收时刻关联 GNSS 卫星状态。首次定位两侧须在配置窗口内看到一致的参与解算卫星集合，否则 INVALID。回调延迟与接收机行为需逐目标机型现场验证。
- 链路、仪器、证据或卫星遥测异常计 INVALID。同一有效样本最多补做两次，超限暂停并安全停机。只有采集、手机链路、场景、功率和 LTE 证据均健康时，无 fix 的观察超时才是 GNSS FAIL。
- 每个运行目录包含 `run.sqlite`、`report.csv`、`report.json`、`report.html`。SQLite 保存尝试、状态变化、原始定位和卫星遥测、设备请求响应与耗时。报告显示 Mock/现场模式、通信模式、校准、场景、LTE 与设备证据、各档成功比和停止原因。设备截图、真实坐标和报告仅保存在授权的现场位置。

## 验证矩阵

| 阶段 | 自动化检查 | 现场补充 |
| --- | --- | --- |
| P0 | uv 锁文件、Windows pytest、Gradle 测试与 APK CI、Mock CLI | Windows 与现场 SDK/ADB 版本 |
| P1 | Kotlin 首次定位、时间戳过滤和卫星关联测试 | 目标机型真实 GNSS、回调延迟、Root 启动准备 |
| P2 | 双向 JSONL 本机 socket、幂等、重复序列、补传测试 | 关箱 USB 授权、稳定性和断线恢复 |
| P3 | PySide6 启停/恢复/历史和 SQLite、CSV/JSON/HTML | 操作员按现场设备填写证据 |
| P4 | Mock 仪器故障及人工确认接口 | 两台仪器的实际状态、命令文档与读回 |
| P5 | 20.3 s / 101.3 m / 4 星边界、18/20 与 19/20、功率下探、停止及恢复 | 真实 LTE + GNSS 全流程以及 USB 干扰 A/B |

## 现场需提供的信息

- **GSS7000**：SimREPLAYplus 版本、授权的 DGP01449AAA 对应章节、远控启用方式、端口与帧格式、场景核验和安全停止命令、绝对功率或偏移量定义、逐档设定及读回示例、停止后 RF 证据、错误响应及允许范围。官方数据表确认选定以太网远控能力，现场版本命令仍待验证。 [Spirent GSS7000 数据表](https://spirentfederal.com/wp-content/uploads/MS7000-Issue-1-24-GSS7000-Series-GNSS-Constellation-Simulator-datasheet-with-product-specification-compressed-1.pdf)
- **CMW500**：型号、固件、LTE 选件、主频小区参数、可确认 DUT 的注册与持续状态日志。若需自动核查，另外提供对应版本的查询接口文档与真实请求、响应、掉线示例。
- **DUT**：机型、芯片、Android 版本、Root 方式、目标启动模式、每轮启动准备和辅助数据策略、定位与 GNSS 回调样本、屏蔽箱关门后的 USB 复连记录。
- **RF 与场景**：静态场景版本/哈希和真值、星座/频段、功率定义与校准平面、线损、耦合与隔离、最低可用功率、关 RF 的实测结果、USB 干扰对照。

P6 用实机和校准记录完成现场验收。P7 的 LTE 数据通道使用未来的 `PhoneTransport` 实现。一期 CMW500 提供 LTE 环境，定位数据走 USB ADB。
