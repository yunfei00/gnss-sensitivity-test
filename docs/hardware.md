# 硬件连接、隔离与检查

## 接线
1. Windows LAN → GSS7000 控制接口；核实使用 SimREPLAYplus 而非 SimTEST。
2. Windows LAN → CMW500 控制接口（若现场支持远控）；一期 CMW500 用于 LTE 主频小区及手机注册。
3. GSS7000 GNSS RF → 屏蔽箱射频穿墙口 → 箱内天线/经授权的 DUT RF 输入。
4. CMW500 LTE RF → 独立射频穿墙口 → 箱内 LTE 天线/经授权的 DUT RF 输入。
5. Windows USB → **支持数据的滤波 USB 穿墙接口** → 箱内短线 → Root 手机；USB 调试授权在关箱前完成。

## 禁止事项
- 禁止从箱门缝直接走 USB 线破坏屏蔽。
- 禁止未评估隔离度、衰减器、最大功率及端口兼容性就将两路 RF 合路。
- 禁止把模拟 GNSS 信号向非屏蔽环境开放辐射。
- 不将设备地址、密码、SIM 配置、客户数据写入公开仓库。

## 首次联调
```powershell
adb devices -l
adb shell su -c id
adb shell dumpsys location
adb forward tcp:18765 tcp:18765
adb forward --list
```
18765 是**本项目自定义 Android 服务端口**，只有 APP 启动监听后才可连接。多设备使用 adb -s SERIAL。先验证穿墙 USB 支持数据传输、屏蔽箱关闭后 ADB 不断链。

## RF 校准记录
记录信号定义（单卫星/单通道/星座合计）、仪器端口功率、线损、箱内天线耦合与参考平面；未建立可追溯校准链时报告“设定功率”，不能直接声称手机天线口真实接收功率。检查 -120 dBm 起始及后续 1 dB 步进是否在仪器有效范围内。

## USB 干扰 A/B
同场景、同手机姿态、同 LTE 条件、相近温度及启动模式，比较 USB 连接与断开本地记录；分别记录 TTFF、误差、成功率及阈值。发现系统性差异时一期数据只作为流程验证，不用于正式认证。
