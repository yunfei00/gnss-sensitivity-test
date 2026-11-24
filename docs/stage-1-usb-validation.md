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

## 2. 安装手机 APP

在 GitHub Actions 选择当前分支最新成功 CI，下载 android-debug Artifact 并解压。使用 adb -s 实际序列号 install -r APK路径 安装。若签名冲突，不要直接卸载含有测试记录的旧 APP；先备份并确认。

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
