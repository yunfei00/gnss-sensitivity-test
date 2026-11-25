package org.gnss.sensitivity

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import net.sf.geographiclib.Geodesic
import org.json.JSONArray
import org.json.JSONObject
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.UUID
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit

class CollectorService : Service() {
    companion object {
        @Volatile var uiSnapshot = CollectorDisplay()
            private set
        @Volatile var running = false
            private set
        @Volatile var rootEvidence = "尚未检测 Root"
    }

    private lateinit var worker: HandlerThread
    private lateinit var handler: Handler
    private lateinit var journal: SQLiteJournal
    private lateinit var location: LocationManager
    @Volatile private var server: ServerSocket? = null
    @Volatile private var client: Socket? = null
    @Volatile private var closed = false
    private var run: String? = null
    private var prepared: String? = null
    private val started = mutableSetOf<String>()
    @Volatile private var active: Attempt? = null
    private var latest = JSONObject()
    private var live = JSONObject()
    private var manual: ManualSession? = null
    private var manualId: String? = null
    private var localStop = false
    private var lastError: String? = null
    private val instanceId = UUID.randomUUID().toString()
    private lateinit var deviceId: String

    override fun onCreate() {
        super.onCreate()
        val notifications = checkNotNull(getSystemService(NotificationManager::class.java))
        notifications.createNotificationChannel(NotificationChannel("gnss", "GNSS 测试", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, CollectorService::class.java).setAction("STOP"),
            PendingIntent.FLAG_IMMUTABLE)
        startForeground(1, Notification.Builder(this, "gnss").setContentTitle(getString(R.string.app_name))
            .setContentText("USB GNSS 采集服务").setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "停止当前试验", stop).build())
            .setSmallIcon(android.R.drawable.ic_menu_mylocation).build())
        location = checkNotNull(getSystemService(LocationManager::class.java))
        val preferences = getSharedPreferences("installation", MODE_PRIVATE)
        deviceId = preferences.getString("id", null) ?: UUID.randomUUID().toString().also {
            check(preferences.edit().putString("id", it).commit())
        }
        journal = SQLiteJournal(this)
        worker = HandlerThread("gnss-events").also { it.start() }
        handler = Handler(worker.looper)
        running = true
        Thread(::serve, "gnss-loopback").start()
        handler.post { refresh() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "START_MANUAL") handler.post { startManual() }
        if (intent?.action == "STOP_MANUAL") handler.post { stopManual(); refresh() }
        if (intent?.action == "STOP_RUN_LOCAL") handler.post {
            localStop = true
            stopActive("USER_STOP")
            prepared = null
            run = null
            refresh()
        }
        if (intent?.action == "STOP") handler.post {
            stopManual()
            localStop = true
            stopActive("USER_STOP")
            prepared = null
            refresh()
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        running = false
        closed = true
        runCatching { server?.close() }
        runCatching { client?.close() }
        handler.post {
            stopManual("SERVICE_STOP")
            stopActive("SERVICE_STOP")
            journal.close()
            uiSnapshot = uiSnapshot.copy(listening = false, connected = false, activeAttempt = null, preparedAttempt = null, manualActive = false)
        }
        worker.quitSafely()
        super.onDestroy()
    }

    private fun serve() {
        val router = CommandRouter(journal, ::control)
        try {
            ServerSocket(18765, 1, InetAddress.getByName("127.0.0.1")).use { listening ->
                server = listening
                if (closed) return
                handler.post { refresh() }
                while (!closed) {
                    listening.accept().use { socket ->
                        client = socket
                        if (closed) return
                        handler.post { refresh() }
                        socket.soTimeout = 5_000
                        runCatching {
                            val input = socket.getInputStream().buffered()
                            val output = socket.getOutputStream().buffered()
                            while (!closed) {
                                val line = input.readFrame { active == null && !closed } ?: break
                                val task = FutureTask {
                                    router.dispatch(line).also { refresh() }.toString()
                                }
                                if (!handler.post(task)) break
                                val response = task.get(4, TimeUnit.SECONDS)
                                output.write((response + "\n").toByteArray(Charsets.UTF_8))
                                output.flush()
                            }
                        }
                    }
                    client = null
                    handler.post {
                        stopActive("TRANSPORT_ERROR")
                        refresh()
                    }
                }
            }
        } catch (error: Exception) {
            if (!closed) handler.post {
                lastError = "TCP: ${error.message}"
                stopActive("TRANSPORT_ERROR")
                refresh()
            }
        }
    }

    private fun startManual() {
        if (manual != null) return
        if (!ready() || active != null || prepared != null || run != null) {
            lastError = "MANUAL_NOT_READY_OR_RUN_CONFIGURED"
            refresh()
            return
        }
        lastError = null
        val id = UUID.randomUUID().toString()
        val session = ManualSession(location, handler, { refresh() }, { reason ->
            lastError = reason
            stopManual(reason)
            refresh()
        }, { kind, body -> journal.appendManual(id, kind, body) })
        manual = session
        manualId = id
        try {
            journal.appendManual(id, "SESSION_START", JSONObject().put("device_id", deviceId))
            session.start()
        } catch (error: Exception) {
            stopManual("MANUAL_START_FAILED")
            lastError = error.message ?: "MANUAL_START_FAILED"
        }
        refresh()
    }

    private fun stopManual(reason: String = "USER_STOP") {
        manual?.stop()
        manual = null
        val id = manualId
        manualId = null
        if (id != null) runCatching {
            journal.appendManual(id, "SESSION_STOP", JSONObject().put("reason", reason))
        }.onFailure { lastError = "MANUAL_JOURNAL_ERROR: ${it.message}" }
    }

    private fun ready(): Boolean =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED &&
            location.isProviderEnabled(LocationManager.GPS_PROVIDER)

    private fun status() = JSONObject()
        .put("ready", ready() && manual == null).put("active_run", run ?: JSONObject.NULL)
        .put("active_attempt", active?.id ?: JSONObject.NULL).put("local_stop", localStop)
        .put("model", "${Build.MANUFACTURER} ${Build.MODEL}").put("android_api", Build.VERSION.SDK_INT)
        .put("android_version", Build.VERSION.RELEASE).put("app_version", "0.1.0").put("root", rootEvidence)
        .put("device_id", deviceId).put("instance_id", instanceId)
        .put("last_error", lastError ?: JSONObject.NULL)

    private fun refresh() {
        manual?.let { session ->
            val fix = session.fix
            uiSnapshot = CollectorDisplay(
                listening = server?.isClosed == false && !closed,
                connected = client?.isClosed == false && !closed,
                manualActive = true, manualAccuracyM = fix?.takeIf { it.hasAccuracy() }?.accuracy?.toDouble(),
                latitude = fix?.latitude, longitude = fix?.longitude, ttff = session.ttff,
                usedInFix = session.satellites.filter { it.used }.distinctBy { it.constellation to it.svid }.size,
                satellites = session.satellites, liveLatitude = fix?.latitude, liveLongitude = fix?.longitude,
                liveFixCount = session.fixCount, lastError = lastError, recordCount = journal.manualCount()
            )
            return
        }
        fun number(key: String) = latest.optDouble(key).takeIf { it.isFinite() }
        fun text(key: String) = latest.optString(key).takeIf { it.isNotBlank() && !latest.isNull(key) }
        val raw = live.optJSONArray("satellites") ?: latest.optJSONArray("satellites")
        val satellites = List(raw?.length() ?: 0) { index ->
            val item = checkNotNull(raw).getJSONObject(index)
            DisplaySatellite(item.getInt("constellation"), item.getInt("svid"),
                item.getDouble("cn0_db_hz"), item.getBoolean("used_in_fix"))
        }
        uiSnapshot = CollectorDisplay(
            listening = server?.isClosed == false && !closed, connected = client?.isClosed == false && !closed,
            activeRun = run, activeAttempt = active?.id, preparedAttempt = prepared, latestAttempt = text("attempt_id"),
            latitude = number("latitude"), longitude = number("longitude"), ttff = number("ttff_s"),
            errorM = number("horizontal_error_m"), usedInFix = number("used_in_fix")?.toInt(),
            satellites = satellites, liveLatitude = live.optDouble("latitude").takeIf { it.isFinite() },
            liveLongitude = live.optDouble("longitude").takeIf { it.isFinite() },
            liveErrorM = live.optDouble("horizontal_error_m").takeIf { it.isFinite() },
            liveAgeMs = live.optLong("age_ms", -1).takeIf { it >= 0 },
            liveFixCount = live.optLong("fix_count", 0), result = text("status"), reason = text("reason"),
            lastError = lastError, recordCount = journal.count()
        )
    }

    private fun control(command: JSONObject): JSONObject {
        val kind = command.getString("type")
        val target = command.getString("run_id")
        val id = command.takeUnless { it.isNull("attempt_id") }?.getString("attempt_id")
        val args = command.getJSONObject("payload")
        when (kind) {
            "HELLO", "GET_STATUS", "PING" -> return status()
            "CONFIGURE_RUN" -> {
                check(ready() && active == null && manual == null) { "GPS disabled, precise location denied, or attempt active" }
                if (run != target) {
                    started.clear()
                    latest = JSONObject()
                    live = JSONObject()
                }
                run = target
                prepared = null
                localStop = false
                lastError = null
            }
            "STOP_RUN" -> if (run == target) {
                stopActive("USER_STOP")
                prepared = null
                run = null
            }
            else -> {
                check(run == target) { "Run must be configured on this service instance" }
                when (kind) {
                    "PREPARE_ATTEMPT" -> {
                        check(ready() && !localStop && active == null && id !in started)
                        val mode = args.getString("startup_mode")
                        require(mode in listOf("HOT", "WARM", "COLD", "AGPS"))
                        require(args.getString("preparation_evidence").isNotBlank()) {
                            "No verified preparation for $mode"
                        }
                        prepared = id
                        latest = JSONObject()
                        live = JSONObject()
                    }
                    "START_ATTEMPT" -> {
                        check(ready() && !localStop && active == null && id == prepared && id !in started)
                        val reference = args.getJSONObject("reference")
                        val lat = reference.getDouble("latitude")
                        val lon = reference.getDouble("longitude")
                        require(lat in -90.0..90.0 && lon in -180.0..180.0)
                        val window = args.getDouble("observation_s")
                        require(window in 20.3..300.0)
                        val tolerance = args.getLong("satellite_tolerance_ms")
                        require(tolerance in 1..2000)
                        val attempt = Attempt(target, checkNotNull(id), lat, lon, window, tolerance)
                        started.add(id)
                        prepared = null
                        latest = JSONObject()
                        live = JSONObject()
                        active = attempt
                        try {
                            attempt.start()
                        } catch (error: Exception) {
                            active = null
                            attempt.release()
                            throw error
                        }
                    }
                    "STOP_ATTEMPT" -> {
                        if (active?.id == id) stopActive("USER_STOP")
                        if (prepared == id) prepared = null
                    }
                }
            }
        }
        return status()
    }

    private fun stopActive(reason: String) {
        active?.complete("INVALID", reason)
    }

    private inner class Attempt(
        val runId: String, val id: String, val lat: Double, val lon: Double,
        val window: Double, val toleranceMs: Long
    ) : LocationListener {
        private var t0 = 0L
        private lateinit var selection: FirstFix
        private var receiverStarted = false
        private var fixCount = 0L
        private var lastFixAtNs = 0L
        private val snapshots = ArrayDeque<SatelliteSnapshot>()
        private val timeout = Runnable {
            guard {
                if (selection.fix == null) {
                    if (ready() && receiverStarted) complete("FAIL", "TIMEOUT")
                    else complete("INVALID", "GNSS_NOT_READY")
                }
            }
        }
        private val settleFix = Runnable {
            guard {
                val satellite = selection.associate(snapshots, toleranceMs * 1_000_000)
                if (!ready() || !receiverStarted || satellite == null) {
                    complete("INVALID", "INVALID_TELEMETRY")
                } else complete("OBSERVED", "FIRST_FIX", satellite)
            }
        }
        private val gnss = object : GnssStatus.Callback() {
            override fun onStarted() = guard { receiverStarted = true }
            override fun onStopped() = guard { complete("INVALID", "GNSS_STOPPED") }
            override fun onFirstFix(ttffMillis: Int) = guard {
                publish("DEVICE_STATUS", JSONObject().put("android_ttff_ms", ttffMillis))
            }
            override fun onSatelliteStatusChanged(status: GnssStatus) = guard {
                receiverStarted = true
                val now = SystemClock.elapsedRealtimeNanos()
                val used = mutableSetOf<Pair<Int, Int>>()
                val satellites = JSONArray()
                for (i in 0 until status.satelliteCount) {
                    val constellation = status.getConstellationType(i)
                    val svid = status.getSvid(i)
                    val inFix = status.usedInFix(i)
                    if (inFix) used.add(constellation to svid)
                    satellites.put(JSONObject().put("constellation", constellation).put("svid", svid)
                        .put("used_in_fix", inFix).put("cn0_db_hz", status.getCn0DbHz(i).toDouble()))
                }
                snapshots.addLast(SatelliteSnapshot(now, used))
                while (snapshots.isNotEmpty() && snapshots.first().receivedNs < now - toleranceMs * 2_000_000) {
                    snapshots.removeFirst()
                }
                publish("SATELLITE_STATUS", JSONObject().put("used_in_fix", used.size)
                    .put("timestamp_basis", "callback_received").put("satellites", satellites), now)
            }
        }

        private val collector = GnssCollector(location, handler, gnss, this)

        fun start() {
            check(ready())
            val duration = (window * 1_000_000_000).toLong()
            collector.start { startedAt ->
                t0 = startedAt
                selection = FirstFix(t0, duration)
            }
            publish("DEVICE_STATUS", JSONObject().put("t0_monotonic_ns", t0), t0)
            handler.postDelayed(timeout, (window * 1000).toLong())
        }

        override fun onLocationChanged(value: Location) = guard {
            val now = SystemClock.elapsedRealtimeNanos()
            val fix = Fix(value.elapsedRealtimeNanos, value.latitude, value.longitude)
            val mock = if (Build.VERSION.SDK_INT >= 31) value.isMock else @Suppress("DEPRECATION") value.isFromMockProvider
            val fresh = !mock && value.provider == LocationManager.GPS_PROVIDER &&
                fix.atNs > t0 && fix.atNs <= now && fix.atNs > lastFixAtNs &&
                fix.latitude in -90.0..90.0 && fix.longitude in -180.0..180.0
            if (fresh) {
                lastFixAtNs = fix.atNs
                fixCount++
                live = JSONObject().put("latitude", fix.latitude).put("longitude", fix.longitude)
                    .put("horizontal_error_m", Geodesic.WGS84.Inverse(lat, lon, fix.latitude, fix.longitude).s12)
                    .put("age_ms", (now - fix.atNs) / 1_000_000)
                    .put("fix_count", fixCount)
            }
            val first = selection.accept(fix, value.provider, mock, now)
            val payload = JSONObject().put("provider", value.provider).put("mock_location", mock)
                .put("location_elapsed_ns", fix.atNs).put("locked_first_fix", first)
            if (fix.latitude.isFinite() && fix.longitude.isFinite()) {
                payload.put("latitude", fix.latitude).put("longitude", fix.longitude)
                .put("fresh", fresh).put("fix_count", fixCount)
            }
            publish("LOCATION_UPDATE", payload, now)
            if (first) {
                publish("FIRST_FIX", metrics(fix), fix.atNs)
                handler.postDelayed(settleFix, toleranceMs)
            }
        }

        override fun onProviderDisabled(provider: String) = guard { complete("INVALID", "GPS_DISABLED") }

        override fun onProviderEnabled(provider: String) = Unit

        @Suppress("DEPRECATION")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit

        private fun metrics(fix: Fix) = JSONObject().put("source", "GPS_PROVIDER")
            .put("latitude", fix.latitude).put("longitude", fix.longitude)
            .put("first_fix_elapsed_realtime_ns", fix.atNs)
            .put("ttff_s", (fix.atNs - t0) / 1e9)
            .put("horizontal_error_m", Geodesic.WGS84.Inverse(lat, lon, fix.latitude, fix.longitude).s12)

        fun release() {
            handler.removeCallbacks(timeout)
            handler.removeCallbacks(settleFix)
            collector.stop()
        }

        fun complete(status: String, reason: String, satellite: SatelliteSnapshot? = null) {
            active = null
            release()
            val fix = if (::selection.isInitialized) selection.fix else null
            val payload = (fix?.let(::metrics) ?: JSONObject())
                .put("t0_monotonic_ns", t0).put("status", status).put("reason", reason)
                .put("integrity", if (status == "INVALID") "INVALID" else "COMPLETE")
            if (satellite != null) payload.put("used_in_fix", satellite.count)
                .put("satellite_elapsed_ns", satellite.receivedNs)
                .put("satellite_association", "POST_FIX_CALLBACK")
            if (status == "INVALID") lastError = reason
            runCatching { publish("ATTEMPT_RESULT", payload) }
                .onFailure { lastError = "JOURNAL_ERROR: ${it.message}" }
            refresh()
        }

        private fun guard(block: () -> Unit) {
            if (active !== this) return
            try {
                block()
            } catch (error: Exception) {
                complete("INVALID", "COLLECTOR_ERROR: ${error.message}")
            }
        }

        private fun publish(type: String, payload: JSONObject, time: Long = SystemClock.elapsedRealtimeNanos()) {
            journal.append(envelope(type, runId, id, payload, monotonicNs = time))
            if (type != "LOCATION_UPDATE" || !payload.optBoolean("mock_location")) {
                val firstLocked = latest.has("first_fix_elapsed_realtime_ns")
                latest.put("attempt_id", id)
                if (type == "ATTEMPT_RESULT" && !payload.has("used_in_fix")) latest.remove("used_in_fix")
                payload.keys().forEach { key ->
                    if (!firstLocked || type != "LOCATION_UPDATE" || key !in setOf("latitude", "longitude")) {
                        latest.put(key, payload.get(key))
                    }
                }
            }
            refresh()
        }
    }
}
