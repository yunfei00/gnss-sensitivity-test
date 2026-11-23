"""Presentation helpers shared by the Windows console and HTML reports."""

STATES = {
    "IDLE": "待开始", "PRECHECK": "设备预检", "SCENARIO_READY": "场景就绪", "LEVEL_SETUP": "设置功率",
    "ATTEMPT_PREPARE": "准备试验", "ATTEMPT_RUNNING": "正在采集", "ATTEMPT_EVALUATE": "判定试验",
    "LEVEL_EVALUATE": "判定档位", "STOPPING": "正在安全停止", "STOPPED": "已停止", "PAUSED": "已暂停",
    "FINISHED": "已完成", "ERROR": "运行异常", "OPEN": "待完成",
    "PASS": "PASS", "FAIL": "FAIL", "INVALID": "INVALID",
}
REASONS = {
    "USER_STOP": "操作员停止", "PHONE_USER_STOP": "手机端停止", "LEVEL_FAILED": "当前档未达标",
    "NOT_PASSED_AT_START": "未在起始档通过", "MIN_POWER_REACHED": "已达到功率下限",
    "MAX_LEVELS_REACHED": "已达到档数上限", "THRESHOLDS_MET": "满足单次判定条件",
    "TIMEOUT": "观察窗口内未定位", "TTFF": "TTFF 超限", "HORIZONTAL_ERROR": "水平误差超限",
    "USED_IN_FIX": "参与解算卫星不足", "UNRELIABLE_USED_IN_FIX": "卫星关联证据不足",
    "INVALID_TELEMETRY": "遥测数据不完整", "TRANSPORT_ERROR": "通信异常",
    "HOST_INTERRUPTED": "上位机运行中断", "HOST_ERROR": "上位机异常",
}


def reason_text(value):
    return " · ".join(REASONS.get(part, part) for part in str(value or "—").split("+"))


def state_text(value):
    return STATES.get(value, value or "—")


def quantity(value, unit="", digits=None):
    if value is None:
        return "—"
    display = str(value) if digits is None else f"{value:.{digits}f}"
    return f"{display} {unit}".strip()
