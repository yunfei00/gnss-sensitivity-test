# 测试流程与判定规则

## 输入
初始功率 -120 dBm；步进 -1 dB；每档有效样本 20；PASS 门槛 19；TTFF ≤20.3 s；水平误差 ≤101.3 m；参与解算卫星数 ≥4；建议最大观察窗口 30 s（配置化）；每次 INVALID 最多重试 2 次，连续设备错误触发安全停止；最低功率和最大档数必须显式配置以避免无限下探。

## 真值与误差
采用 WGS84 地球模型的测地线逆解，计算手机首次有效定位坐标与 SimREPLAYplus 场景静态真值之间的地表距离，单位 m。Android Location.getAccuracy() 是估计不确定度，不是本测试的水平定位误差。坐标系、精度及场景时间必须一致。

## 首次定位
- APP 在开始 GNSS request 前记录 SystemClock.elapsedRealtimeNanos() 为 t0。
- 仅接受本次 request 之后生成、来自 GPS_PROVIDER 的新鲜有效 fix；拒绝 lastKnownLocation、Mock location、无效坐标、旧时间戳。
- TTFF=(fix.elapsedRealtimeNanos - t0)/1e9；onFirstFix(ttffMillis) 仅辅助诊断。
- 以时间戳关联 GnssStatus.usedInFix() 与首次 fix；缺失或无法可靠匹配记 INVALID，并保存原始卫星事件供诊断。
- TTFF>20.3 s、误差>101.3 m、卫星<4 任一条件则 FAIL；超过观察窗口未定位记 TIMEOUT（属于 GNSS FAIL，前提是设备和采集链路健康）。
- 每轮只锁定首次符合有效性定义的 fix，不能用后续更好的 fix 改写首次结果。

## 功率循环
```text
precheck GSS/CMW/phone
verify static scenario and reference position
power = -120
while power >= configured_min_power:
  set_power(power); verify_readback_and_settle()
  successes = 0; valid_trials = 0
  while valid_trials < 20:
    prepare_phone_start_mode(); verify_preparation()
    start_attempt(); collect_first_fix_or_timeout()
    if control/telemetry invalid: retry bounded; else valid_trials += 1
    if PASS: successes += 1
    persist attempt, evidence, decision
    if successes + (20-valid_trials) < 19: # 已不可能达标，可配置提前终止；默认仍记录规则
       optional early stop of level with explicit reason
  if successes < 19: finish(last_passing_power or NOT_PASSED_AT_START)
  else: last_passing_power = power; power -= 1
```
默认应完成每档 20 次有效试验，除非用户显式启用提前判失败且报告清楚标注。测试期间 GNSS 场景持续运行，档内不变功率；是否能在连续场景下复现指定启动模式，必须现场验证。

## 安全与恢复
用户停止：先禁止新 attempt，取消当前请求、持久化未完成状态，再安全结束；不得把 STOP/INVALID 计入失败。重启恢复须读取真实仪器功率与场景、CMW500 LTE 状态、手机 attempt 状态，确认一致后才允许继续。未知状态优先暂停而非盲目继续。
