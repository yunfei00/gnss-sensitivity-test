package org.gnss.sensitivity

import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.SystemClock

internal class ManualSession(
    location: LocationManager,
    handler: Handler,
    private val changed: (ManualSession) -> Unit,
    private val failed: (String) -> Unit,
    private val record: (String, org.json.JSONObject) -> Unit
) : LocationListener {
    var satellites: List<DisplaySatellite> = emptyList()
        private set
    var fix: Location? = null
        private set
    var ttff: Double? = null
        private set
    var fixCount = 0L
        private set
    private var t0 = 0L
    private var running = false
    private val callback = object : GnssStatus.Callback() {
        override fun onSatelliteStatusChanged(status: GnssStatus) {
            if (!running) return
            satellites = List(status.satelliteCount) { i ->
                DisplaySatellite(status.getConstellationType(i), status.getSvid(i),
                    status.getCn0DbHz(i).toDouble(), status.usedInFix(i))
            }
            persist("SATELLITE_STATUS", org.json.JSONObject().put("satellites", org.json.JSONArray().apply {
                satellites.forEach { sat -> put(org.json.JSONObject().put("constellation", sat.constellation)
                    .put("svid", sat.svid).put("cn0_db_hz", sat.cn0).put("used_in_fix", sat.used)) }
            }))
            if (running) changed(this@ManualSession)
        }
    }
    private val collector = GnssCollector(location, handler, callback, this)

    fun start() {
        check(!running)
        running = true
        try {
            collector.start { t0 = it }
        } catch (error: Exception) {
            stop()
            throw error
        }
    }

    fun stop() {
        running = false
        collector.stop()
    }

    override fun onLocationChanged(value: Location) {
        if (!running) return
        val mock = if (android.os.Build.VERSION.SDK_INT >= 31) value.isMock
            else @Suppress("DEPRECATION") value.isFromMockProvider
        val time = value.elapsedRealtimeNanos
        if (!ManualPolicy.fresh(value.provider, mock, time, t0, SystemClock.elapsedRealtimeNanos(),
            fix?.elapsedRealtimeNanos ?: 0L, value.latitude, value.longitude)) return
        if (ttff == null) ttff = (time - t0) / 1e9
        fix = Location(value)
        fixCount++
        persist("LOCATION_UPDATE", org.json.JSONObject().put("latitude", value.latitude)
            .put("longitude", value.longitude).put("location_elapsed_ns", time)
            .put("accuracy_m", if (value.hasAccuracy()) value.accuracy.toDouble() else org.json.JSONObject.NULL)
            .put("ttff_s", ttff).put("fix_count", fixCount))
        if (running) changed(this)
    }

    private fun persist(kind: String, body: org.json.JSONObject) {
        try {
            record(kind, body)
        } catch (error: Exception) {
            failed("MANUAL_JOURNAL_ERROR: ${error.message}")
        }
    }

    override fun onProviderDisabled(provider: String) {
        if (running && provider == LocationManager.GPS_PROVIDER) failed("GPS_DISABLED")
    }
    override fun onProviderEnabled(provider: String) = Unit
    @Suppress("DEPRECATION")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
}
