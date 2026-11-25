# 手机—上位机通信协议 v1

## 传输
一期 Android loopback TCP server :18765，Windows 经 adb forward tcp:18765 tcp:18765 连接；UTF-8 JSON Lines（每行一个 JSON）。二期保留同样应用层消息，改为 LTE IP TCP 传输，加入设备认证与加密。所有请求/事件含 protocol_version、run_id、attempt_id、message_id、seq、utc_timestamp、monotonic_ns（若适用）。

## 指令
HELLO、GET_STATUS、CONFIGURE_RUN、PREPARE_ATTEMPT、START_ATTEMPT、STOP_ATTEMPT、STOP_RUN、FETCH_EVENTS、ACK、PING。控制命令按 message_id 幂等；重复命令不得重复启动定位。

## 事件
DEVICE_STATUS、SATELLITE_STATUS、LOCATION_UPDATE、FIRST_FIX、ATTEMPT_RESULT、ERROR、HEARTBEAT。ATTEMPT_RESULT 必须提供原始字段、结果、失败原因、数据完整性状态。心跳/断线不直接算 GNSS FAIL。

## 示例
```json
{"protocol_version":1,"type":"START_ATTEMPT","run_id":"run-001","attempt_id":"p-120-r01","message_id":"cmd-001","seq":1,"utc_timestamp":"2026-11-23T00:00:00Z","payload":{"startup_mode":"HOT","reference":{"latitude":39.916527,"longitude":116.397128}}}
{"protocol_version":1,"type":"ATTEMPT_RESULT","run_id":"run-001","attempt_id":"p-120-r01","message_id":"evt-001","seq":2,"utc_timestamp":"2026-11-23T00:00:09Z","payload":{"power_dbm":-120,"latitude":39.916527,"longitude":116.397128,"horizontal_error_m":11.32,"ttff_s":8.6,"used_in_fix":7,"status":"PASS","source":"GPS_PROVIDER","first_fix_elapsed_realtime_ns":1000000000}}
```
示例坐标、功率、时间和结果均为虚构数据，不能用于硬件验收。真实 first_fix_elapsed_realtime_ns 应大于该轮 t0；示例仅展示字段格式。

## 错误与可靠性
错误分类：GNSS_FAIL / TIMEOUT / INVALID_TELEMETRY / DEVICE_ERROR / TRANSPORT_ERROR / USER_STOP / CONFIG_ERROR。每个结果写入本地持久化后 ACK；Windows 按 run_id+attempt_id+message_id 去重。断线重连通过 FETCH_EVENTS(last_ack_seq) 补传。版本不兼容明确拒绝，不做静默降级。

P0–P5 实现中，每条请求收到一条同步 JSONL 业务响应。响应使用 `DEVICE_STATUS` 或 `ERROR`，`seq=0`，`payload.response_to` 为原请求消息 ID。手机持久事件按递增 `seq` 编号，FETCH 的响应在 `payload.events` 中最多返回 24 条，ACK 通过 `payload.seq` 确认已提交游标。服务保留原始事件供审计；各 run 的序列号可有空档。重发状态改变指令需保持原消息及其 ID，消息 ID 冲突会拒绝。活动采集在 TCP 连接退出或读取超时后停止，已落盘记录可以补传。等待操作员确认时若没有活动采集，正常空闲不会断开连接。

ATTEMPT_RESULT 的 `integrity` 为 `COMPLETE` 或 `INVALID`。获得首次定位时使用 `status=OBSERVED`，包含手机 t0、首次定位时间戳、坐标、来源、卫星时间戳及关联依据，Windows 根据原始字段独立计算 PASS/FAIL。采集健康且观察窗口无定位时使用 `FAIL/TIMEOUT`。停止时保留 INVALID 及原因。

## 时钟
手机内部用单调时钟计算 TTFF；上位机与手机 UTC 仅用于事件排序审计；需要同步时记录 RTT 和偏差估计，不能直接跨设备时间相减测 TTFF。
