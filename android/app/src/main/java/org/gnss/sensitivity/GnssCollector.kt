package org.gnss.sensitivity

import android.annotation.SuppressLint
import android.location.GnssStatus
import android.location.LocationListener
import android.location.LocationManager
import android.os.Handler
import android.os.SystemClock

/** Handler-confined registration lifecycle shared by collection sessions. */
internal class GnssCollector(
    private val location: LocationManager,
    private val handler: Handler,
    private val gnss: GnssStatus.Callback,
    private val listener: LocationListener,
    private val diagnostic: (org.json.JSONObject) -> Unit = {}
) {
    private var registered = false
    private var requested = false
    private val diagnostics = GnssDiagnostics(location, handler, diagnostic)

    @SuppressLint("MissingPermission")
    fun start(beforeRequest: (Long) -> Unit) {
        check(!registered && !requested)
        try {
            check(location.registerGnssStatusCallback(gnss, handler))
            registered = true
            beforeRequest(SystemClock.elapsedRealtimeNanos())
            diagnostics.start()
            requested = true
            location.requestLocationUpdates(LocationManager.GPS_PROVIDER, 0L, 0f, listener, handler.looper)
        } catch (error: Exception) {
            stop()
            throw error
        }
    }

    fun stop() {
        diagnostics.stop()
        if (requested) {
            requested = false
            runCatching { location.removeUpdates(listener) }
        }
        if (registered) {
            registered = false
            runCatching { location.unregisterGnssStatusCallback(gnss) }
        }
    }
}
