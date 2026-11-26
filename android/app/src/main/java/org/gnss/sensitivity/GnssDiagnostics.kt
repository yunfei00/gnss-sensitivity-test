package org.gnss.sensitivity

import android.annotation.SuppressLint
import android.location.GnssMeasurementsEvent
import android.location.LocationManager
import android.location.OnNmeaMessageListener
import android.os.Handler
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject

/** Optional diagnostics must not prevent a receiver from starting. */
internal class GnssDiagnostics(private val location: LocationManager, private val handler: Handler,
                               private val record: (JSONObject) -> Unit) {
    private var running = false
    private var rawRegistered = false
    private var nmeaRegistered = false
    private val nmea = OnNmeaMessageListener { message, timestamp ->
        if (running) record(JSONObject().put("kind", "nmea").put("utc_ms", timestamp).put("sentence", message))
    }
    private val raw = object : GnssMeasurementsEvent.Callback() {
        override fun onGnssMeasurementsReceived(event: GnssMeasurementsEvent) {
            if (!running) return
            val clock = event.clock
            val body = JSONObject().put("kind", "measurements")
                .put("received_elapsed_ns", SystemClock.elapsedRealtimeNanos())
                .put("clock_time_ns", clock.timeNanos)
                .put("hardware_clock_discontinuity_count", clock.hardwareClockDiscontinuityCount)
            if (clock.hasFullBiasNanos()) body.put("full_bias_ns", clock.fullBiasNanos)
            if (clock.hasBiasNanos() && clock.biasNanos.isFinite()) body.put("bias_ns", clock.biasNanos)
            body.put("measurements", JSONArray().apply {
                event.measurements.forEach { measurement ->
                    put(JSONObject().put("svid", measurement.svid).put("constellation", measurement.constellationType)
                        .put("state", measurement.state).put("received_sv_time_ns", measurement.receivedSvTimeNanos)
                        .put("received_sv_time_uncertainty_ns", measurement.receivedSvTimeUncertaintyNanos)
                        .put("cn0_db_hz", measurement.cn0DbHz.takeIf { it.isFinite() } ?: JSONObject.NULL)
                        .put("pseudorange_rate_mps", measurement.pseudorangeRateMetersPerSecond.takeIf { it.isFinite() } ?: JSONObject.NULL))
                }
            })
            record(body)
        }
        override fun onStatusChanged(status: Int) {
            if (running) record(JSONObject().put("kind", "measurements_status").put("status", status))
        }
    }

    @SuppressLint("MissingPermission")
    fun start() {
        running = true
        rawRegistered = runCatching { location.registerGnssMeasurementsCallback(raw, handler) }.getOrDefault(false)
        nmeaRegistered = runCatching { location.addNmeaListener(nmea, handler) }.getOrDefault(false)
        record(JSONObject().put("kind", "registration").put("raw_registered", rawRegistered)
            .put("nmea_registered", nmeaRegistered))
    }

    fun stop() {
        running = false
        if (rawRegistered) runCatching { location.unregisterGnssMeasurementsCallback(raw) }
        if (nmeaRegistered) runCatching { location.removeNmeaListener(nmea) }
        rawRegistered = false
        nmeaRegistered = false
    }
}
