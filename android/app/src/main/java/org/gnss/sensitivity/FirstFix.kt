package org.gnss.sensitivity


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

    // Satellite callbacks are asynchronous. A fast HOT fix may precede the first
    // satellite callback; use the earliest post-fix snapshot within tolerance.
    // Never attribute a snapshot from before this attempt to the new fix.
    // Require at least one satellite used in the solution.
    fun associate(snapshots: Iterable<SatelliteSnapshot>, toleranceNs: Long): SatelliteSnapshot? {
        val atNs = fix?.atNs ?: return null
        return snapshots.filter {
            it.receivedNs >= atNs && it.receivedNs >= startNs &&
                it.receivedNs - atNs <= toleranceNs && it.used.isNotEmpty()
        }.minByOrNull { it.receivedNs }
    }
}

/** A location is provisional until a subsequent satellite callback confirms use. */
internal class SatelliteConfirmedFix(private val startNs: Long, private val windowNs: Long,
                                     private val toleranceNs: Long) {
    private var pending: Fix? = null
    var firstSatelliteFix: Fix? = null
        private set
    var fix: Fix? = null
        private set

    fun offer(candidate: Fix, provider: String?, mock: Boolean, now: Long) {
        if (fix != null || (pending?.atNs ?: startNs) >= candidate.atNs) return
        val validator = FirstFix(startNs, windowNs)
        if (validator.accept(candidate, provider, mock, now)) pending = candidate
    }

    fun confirm(snapshot: SatelliteSnapshot): Fix? {
        val candidate = pending ?: return null
        if (fix != null || snapshot.receivedNs < candidate.atNs) return null
        pending = null
        if (snapshot.used.isEmpty() || snapshot.receivedNs - candidate.atNs > toleranceNs) return null
        if (firstSatelliteFix == null) firstSatelliteFix = candidate
        if (snapshot.count < 4) return null
        fix = candidate
        return candidate
    }
}
