# Android APP 技术规范

## 技术栈
Kotlin + Android SDK；前台 GNSS 测试 Service；LocationManager.GPS_PROVIDER、GnssStatus.Callback、SystemClock.elapsedRealtimeNanos；SQLite/Room 或原子文件日志；单线程事件序列化。支持 Root，但基础采集不依赖 Root。

## 功能
- 采集经纬度、定位时间、Location 来源、水平误差（使用上位机下发真值）、首次 TTFF、usedInFix 卫星数、C/N0 与卫星列表。
- 区分 STARTUP_MODE：HOT/WARM/COLD/AGPS；Root 执行前检测机型及支持情况，保留每个复位步骤的命令、退出码、前后状态证据。禁止仅凭 Root 成功就宣称完成真正冷启动。
- 先写本地事件日志，后推送上位机；断线重传、消息序列号、ACK 去重。
- 只监听 loopback TCP 端口 18765，经 ADB forward 使用；一期不开放手机网络监听端口。二期新增可认证的 LTE 通道，不能复用无认证公网监听。
- 服务异常或权限不足时发送 INVALID/ERROR；不能生成伪造的 PASS。

## 权限与平台
检查定位权限、前台服务类型、后台限制、定位开关、开发者选项、USB 调试授权。Android API 版本差异要有兼容层和实机验收。

## TTFF/卫星数
单调时钟 t0 到首次真实新鲜 fix；保存原始事件与关联置信度。GnssStatus 的状态不一定与 fix 同步，无法证明 usedInFix 对应本次首次 fix 时标记 INVALID。

## APP 界面
设备/权限诊断、GNSS 状态、当前测试 ID、当前轮次、经纬度、误差、TTFF、usedInFix、最近错误、本地记录数量；可手动停止。屏蔽箱关门后由 Windows 控制，不依赖人工点击。
