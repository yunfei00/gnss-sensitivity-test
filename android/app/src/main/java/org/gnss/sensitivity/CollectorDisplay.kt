package org.gnss.sensitivity

data class DisplaySatellite(val constellation: Int, val svid: Int, val cn0: Double, val used: Boolean)

data class CollectorDisplay(
    val listening: Boolean = false,
    val connected: Boolean = false,
    val activeRun: String? = null,
    val activeAttempt: String? = null,
    val preparedAttempt: String? = null,
    val latestAttempt: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val ttff: Double? = null,
    val errorM: Double? = null,
    val usedInFix: Int? = null,
    val satellites: List<DisplaySatellite> = emptyList(),
    val liveLatitude: Double? = null,
    val liveLongitude: Double? = null,
    val liveErrorM: Double? = null,
    val liveAgeMs: Long? = null,
    val liveFixCount: Long = 0,
    val result: String? = null,
    val reason: String? = null,
    val lastError: String? = null,
    val recordCount: Long = 0,
) {
    fun phase(): String = when {
        activeAttempt != null -> "正在采集"
        preparedAttempt != null -> "等待上位机开始"
        connected -> "上位机已连接"
        listening -> "等待 USB ADB 连接"
        else -> "采集服务未启动"
    }
}
