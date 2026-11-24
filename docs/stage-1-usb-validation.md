# 阶段一：真实 USB 手机独立联调

本阶段无需 GSS7000 或 CMW500。仅验证真实手机通信和 GNSS 采集，不产生灵敏度结论，不执行清除辅助数据或芯片复位。

## 1. Windows 更新与启动

在已有仓库根目录 PowerShell 执行：

```powershell
git switch codex/phase-1
git pull --ff-only
uv sync --locked
adb version
adb devices -l
uv run --locked python -m desktop
```

ADB 使用较新的 Android SDK Platform Tools，加入 PATH；如需指定路径，设置 GNSS_ADB 环境变量。

## 2. Windows 本地构建与安装手机 APP（推荐）

### 首次配置（只需一次）

安装 [JDK 17](https://adoptium.net/temurin/releases/?version=17)、[Gradle 8.9](https://gradle.org/releases/)（解压 binary ZIP）和 [Android Studio](https://developer.android.com/studio)（用于 SDK Manager，也可使用独立 SDK 命令行工具）。SDK Manager 安装 Android SDK Platform 35、Build Tools 34.0.0、Platform Tools；接受 SDK 许可。设置 JAVA_HOME 为 JDK 根目录、ANDROID_HOME 为 SDK 根目录，将 JDK bin、Gradle 8.9 bin、SDK platform-tools 加入 Windows PATH。重新打开 PowerShell。

例如（路径按实际安装位置修改，仅影响当前 PowerShell）：

```powershell
$env:JAVA_HOME = 'C:\Java\jdk-17'
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:Path = "$env:JAVA_HOME\bin;C:\Tools\gradle-8.9\bin;$env:ANDROID_HOME\platform-tools;$env:Path"
java -version
gradle --version
adb version
Test-Path "$env:ANDROID_HOME\platforms\android-35\android.jar"
Test-Path "$env:ANDROID_HOME\build-tools\34.0.0\aapt2.exe"
```

确认 Java 17、Gradle 8.9，两个 Test-Path 均为 True。长期使用可在 Windows 系统环境变量中保存这些设置。

### 每次更新、构建、安装

在仓库根目录执行（先将 SERIAL 替换为 adb devices -l 显示的目标手机序列号）：

```powershell
git switch codex/phase-1
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git 更新失败' }
.\android\build-debug.ps1
adb devices -l
$serial = 'SERIAL'
adb -s $serial install -r .\android\app\build\outputs\apk\debug\app-debug.apk
if ($LASTEXITCODE -ne 0) { throw 'APK 安装失败' }
adb -s $serial shell am start -n org.gnss.sensitivity/.MainActivity
```

现有脚本执行 testDebugUnitTest、lintDebug、assembleDebug，失败时抛出错误，不继续安装。若脚本执行策略阻止运行，可在当前会话执行 Set-ExecutionPolicy -Scope Process RemoteSigned（遵守公司策略）。Gradle 未加入 PATH 可传入 -Gradle 和 gradle.bat 完整路径。

首次构建需要访问 Google Maven、Maven Central 和 Gradle Plugin Portal。后续复用本机 Gradle 缓存；依赖全部缓存后，可在仓库根目录执行 gradle -p android --offline testDebugUnitTest lintDebug assembleDebug。缺少依赖时离线构建会失败，恢复联网即可。HTTP 429 时等待限流解除再重试，不要删除缓存或随意更改依赖版本。

APK 路径：android/app/build/outputs/apk/debug/app-debug.apk。保留本机默认调试签名（通常为用户目录 .android/debug.keystore），后续同一签名可覆盖安装。若之前安装 CI APK，可能签名不同，出现 INSTALL_FAILED_UPDATE_INCOMPATIBLE；先备份记录并确认后再卸载旧包，卸载会删除 APP 数据。不要将签名密钥提交到 GitHub。

### 备用：GitHub Actions 下载

在 GitHub Actions 选择当前分支最新成功 CI，下载 android-debug Artifact 并解压。使用 adb -s 实际序列号 install -r APK路径 安装。本地构建不依赖 CI 成功，但项目阶段验收仍要求 CI 全绿。

开启开发者选项、USB 调试、系统定位；手机允许 USB 调试授权。打开 APP，授予精确定位，点击“启动 USB 采集”。建议在室外开阔处测试，不要关入屏蔽箱。

## 3. 独立调试

打开 Windows 的“设备调试”页。顶部下拉框自动发现 USB 手机；一台自动选中，多台明确选择。此页不需要切换现场模式或填写仪器参数。

依次点击：
1. 打开 APP：确认手机出现 APP 界面。
2. Root 检测：查看实际 id 输出；uid=0 才证明 Root。
3. 连接 / 状态：确认 HELLO 和 PING 返回，ready=true，型号及安装标识正确。
4. 启动定位采集：观察 SATELLITE_STATUS、LOCATION_UPDATE、FIRST_FIX、ATTEMPT_RESULT。最多观察 60 秒，首次定位完成后自动停止；可手动停止。
5. 再执行一次采集，确认新试验 ID；测试期间插入第二台手机，确认选择锁定。
6. 采集期间拔掉当前 USB，确认出现错误且不切换设备。重新插入后重新手动开始。

日志位于 results/usb-debug/usb-debug-*.jsonl（或 GNSS_RESULTS_DIR 指定目录）。日志含真实位置，只保留在授权本地。诊断使用占位参考坐标，Windows 删除对应误差字段；手机界面的误差在此阶段没有意义。HOT 标签仅满足现有协议，不证明真实热启动。没有定位时先检查天空条件、权限和手机 GNSS 状态。

## 4. 验收记录

逐项记录 PASS/FAIL：APK 安装、USB 单设备、多设备、Root、HELLO/PING、真实卫星遥测、首次新鲜定位、TTFF、参与解算卫星、停止、掉线、重新连接。保存本地日志；不要提交客户位置或设备信息到公开仓库。

CI 通过仅证明自动测试，不代表上述实机验收完成。阶段一通过后才进入 GSS7000 独立控制。

## USB 搜索与排查

现场界面仅支持真实 USB。顶部“搜索 USB 设备”立即请求后台刷新；“输入序列号”按 adb devices 显示的序列号重新搜索，只有确认在线 USB 且传输标识有效才允许使用。鼠标悬停状态可查看 ADB 路径和扫描诊断。优先使用 ADB 类型跟踪，无法识别时回退到 adb devices -l 和 adb -d get-serialno。多台设备若旧版 ADB 不提供 USB 类型，先仅连接目标手机或更新 Platform Tools。历史 Mock 记录可查看但不能恢复。

## 设备调试结构化显示

设备状态、实时定位、卫星明细与原始日志分区显示。Root 检测先检查 adb shell id，再检查 su -c id；未确认 Root 不影响基础定位。连接状态是最近一次命令验证结果，并非持续连接；手机必须手动启动 USB 采集服务。定位采集仍在首次定位完成后自动结束，最多观察 60 秒。卫星表显示实时回调，最终解算数量以结果事件为准。顶部安全停止也可停止独立采集。切换设备清除旧设备指标。
