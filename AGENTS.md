# Codex 开发规范

1. 先读 README.md 与 docs/ 下全部规范，再制定阶段任务。优先 P0→P6，一期完整闭环后才做 P7。
2. 仓库公开：不得提交凭据、内网 IP、真实客户数据、商业手册原文、私有安装包；提供 .env.example 与 .gitignore。
3. 目标 Windows PySide6 上位机 + Kotlin Android APP；Python 用 uv/pytest，Android 用 Gradle；必须可在无仪器环境 Mock 测试。
4. 严格遵循 SimREPLAYplus（不是 SimTEST）接口边界。未经现场验证的 GSS7000/CMW500 命令不得伪装为可运行代码；提供接口桩、模拟器、明确的硬件待验证清单。
5. CMW500 一期必须作为 LTE 网络环境存在，但定位数据一期走 USB ADB；二期才替换为 LTE TCP。
6. 保持 PhoneTransport 抽象和版本化协议，GNSS 测试核心不得依赖具体通信方式。
7. TTFF 用手机单调时钟；水平误差用 WGS84 测地线与静态真值计算；首次 fix 只锁定一次；usedInFix 不可靠时 INVALID。
8. 设备/链路异常不计入 20 次有效样本；用户停止需真正停止，恢复前验证仪器与手机状态。
9. 代码改动必须有对应测试，运行 Windows/Python/Android CI，失败持续修复直到全绿；未实际执行的验证必须注明。
10. 不直接合并未经 CI 验证的 PR；保留清晰提交历史和中文使用说明。
