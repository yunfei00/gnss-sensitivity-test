package org.gnss.sensitivity

import kotlin.math.abs

data class Fix(val atNs: Long, val latitude: Double, val longitude: Double)
data class SatelliteSnapshot(val receivedNs: Long, val used: Set<Pair<Int, Int>>) {
    val count get() = used.size
}

class FirstFix(private val startNs: Long, private val windowNs: Long) {
    var fix: Fix? = null
        private set

    fun accept(candidate: Fix, provider: String?, mock: Boolean, receivedNs: Long): Boolean {
        if (fix != null || mock || provider != "gps" || candidate.atNs <= startNs ||
            candidate.atNs - startNs > windowNs || candidate.atNs > receivedNs ||
            candidate.latitude !in -90.0..90.0 || candidate.longitude !in -180.0..180.0) return false
        fix = candidate
        return true
    }

    fun associate(snapshots: Iterable<SatelliteSnapshot>, toleranceNs: Long): SatelliteSnapshot? {
        val atNs = fix?.atNs ?: return null
        val nearby = snapshots.filter {
            it.receivedNs >= startNs && abs(it.receivedNs - atNs) <= toleranceNs
        }
        val before = nearby.lastOrNull { it.receivedNs <= atNs } ?: return null
        val after = nearby.firstOrNull { it.receivedNs >= atNs } ?: return null
        if (nearby.any { it.used != before.used }) return null
        return if (atNs - before.receivedNs <= after.receivedNs - atNs) before else after
    }
}
