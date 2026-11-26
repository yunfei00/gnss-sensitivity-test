package org.gnss.sensitivity

internal object ManualPolicy {
    fun canStart(ready: Boolean, active: Boolean, prepared: Boolean, configured: Boolean): Boolean =
        ready && !active && !prepared && !configured

    fun fresh(provider: String?, mock: Boolean, time: Long, start: Long, now: Long,
              previous: Long, latitude: Double, longitude: Double): Boolean =
        !mock && provider == "gps" && time > start && time <= now && time > previous &&
            latitude in -90.0..90.0 && longitude in -180.0..180.0
}
