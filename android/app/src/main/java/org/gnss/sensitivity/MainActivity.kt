package org.gnss.sensitivity

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.view.WindowInsets
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.util.Locale
import java.util.concurrent.TimeUnit

class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val backgroundColor = 0xffeef2f7.toInt()
    private val ink = 0xff17283e.toInt()
    private val muted = 0xff50647b.toInt()
    private val accent = 0xff1956a5.toInt()
    private val navy = 0xff142941.toInt()
    private val danger = 0xff9d3328.toInt()
    private lateinit var monitorView: LinearLayout
    private lateinit var diagnosticsView: LinearLayout
    private lateinit var monitorTab: Button
    private lateinit var diagnosticsTab: Button
    private lateinit var phase: TextView
    private lateinit var connection: TextView
    private lateinit var identifiers: TextView
    private lateinit var ttff: TextView
    private lateinit var error: TextView
    private lateinit var used: TextView
    private lateinit var records: TextView
    private lateinit var coordinates: TextView
    private lateinit var result: TextView
    private lateinit var livePosition: TextView
    private lateinit var satellites: TextView
    private lateinit var systemChecks: TextView
    private lateinit var rootStatus: TextView
    private lateinit var start: Button
    private lateinit var stop: Button
    private lateinit var probe: Button
    private lateinit var scroll: ScrollView
    private lateinit var manualModeButton: Button
    private lateinit var autoModeButton: Button
    private lateinit var accuracyLabel: TextView
    private var manualMode = true
    private var requestingService = false
    private var showDiagnostics = false
    private var probing = false

    private val update = object : Runnable {
        override fun run() {
            render()
            ui.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        manualMode = savedInstanceState?.getBoolean("manualMode") ?: true
        val content = column()
        content.setBackgroundColor(backgroundColor)
        if (Build.VERSION.SDK_INT >= 35) {
            content.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                val appearance = android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                    android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
                view.windowInsetsController?.setSystemBarsAppearance(appearance, appearance)
                insets
            }
        } else {
            window.statusBarColor = navy
            window.navigationBarColor = navy
        }
        val header = column(6).apply {
            setBackgroundColor(navy)
            setPadding(dp(20), dp(16), dp(20), dp(18))
        }
        header.addView(text(getString(R.string.app_name), 22, Color.WHITE, true))
        header.addView(text("Android GNSS · 独立采集 / 自动化测试", 13, 0xffc7d7eb.toInt()))
        content.addView(header)

        val tabs = LinearLayout(this).apply { setPadding(dp(16), dp(8), dp(16), dp(2)) }
        monitorTab = action("采集监控") { openPage(false) }
        diagnosticsTab = action("设备诊断") { openPage(true) }
        tabs.addView(monitorTab, weighted())
        tabs.addView(diagnosticsTab, weighted())
        content.addView(tabs)

        val pages = column()
        monitorView = buildMonitor()
        diagnosticsView = buildDiagnostics()
        pages.addView(monitorView)
        pages.addView(diagnosticsView)
        scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(pages)
        }
        content.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(content)
        openPage(savedInstanceState?.getBoolean("diagnostics") ?: false)
        render()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("diagnostics", showDiagnostics)
        outState.putBoolean("manualMode", manualMode)
        super.onSaveInstanceState(outState)
    }

    private fun buildMonitor() = page().apply {
        addView(card("工作模式").apply {
            val modes = LinearLayout(this@MainActivity)
            manualModeButton = action("独立采集") { manualMode = true; render() }
            autoModeButton = action("自动化测试") { manualMode = false; render() }
            modes.addView(manualModeButton, weighted())
            modes.addView(autoModeButton, weighted())
            addView(modes)
        })
        addView(card("连接与控制").apply {
            phase = text("", 20, ink, true)
            connection = text("", 13, muted)
            addView(phase)
            addView(connection)
            val controls = LinearLayout(this@MainActivity)
            start = action("开始采集") { requestCollector() }
            stop = action("停止当前试验") {
                if (CollectorService.running) {
                    startService(Intent(this@MainActivity, CollectorService::class.java).setAction(if (manualMode) "STOP_MANUAL" else "STOP_RUN_LOCAL"))
                }
            }
            styleButton(start, accent, Color.WHITE)
            styleButton(stop, 0xfffbeeea.toInt(), danger)
            controls.addView(start, weighted())
            controls.addView(stop, weighted())
            addView(controls)
        })
        addView(card("试验与定位").apply {
            identifiers = text("", 13, muted).also { it.setTextIsSelectable(true) }
            addView(identifiers)
            val line = LinearLayout(this@MainActivity)
            ttff = metric(line, "首次定位 TTFF")
            error = metric(line, "水平误差")
            accuracyLabel = (error.parent as LinearLayout).getChildAt(0) as TextView
            used = metric(line, "解算卫星")
            addView(line)
            coordinates = text("", 13, muted)
            result = text("", 13, ink, true)
            addView(coordinates)
            addView(result)
        })
        addView(card("实时定位（本轮）").apply {
            livePosition = text("等待新的 GPS 定位", 14, ink).also { it.setTextIsSelectable(true) }
            addView(livePosition)
        })
        addView(card("卫星信号").apply {
            satellites = text("", 13, ink)
            addView(satellites)
        })
    }

    private fun buildDiagnostics() = page().apply {
        addView(card("设备与权限").apply {
            systemChecks = text("", 14, ink)
            addView(systemChecks)
            addView(action("打开系统定位设置") {
                startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS))
            })
        })
        addView(card("本机记录").apply {
            records = text("", 14, ink)
            addView(records)
        })
        addView(card("Root 诊断").apply {
            addView(text("用于需要芯片复位的机型准备。基础 GNSS 采集使用 Android 定位权限。", 13, muted))
            rootStatus = text("", 13, ink).also { it.setTextIsSelectable(true) }
            addView(rootStatus)
            probe = action("检测 Root") {
                probing = true
                render()
                Thread({
                    probeRoot()
                    ui.post {
                        probing = false
                        if (!isFinishing && !isDestroyed) render()
                    }
                }, "root-diagnostics").start()
            }
            addView(probe)
        })
    }

    private fun openPage(diagnostics: Boolean) {
        showDiagnostics = diagnostics
        monitorView.visibility = if (diagnostics) View.GONE else View.VISIBLE
        diagnosticsView.visibility = if (diagnostics) View.VISIBLE else View.GONE
        for ((tab, selected) in listOf(monitorTab to !diagnostics, diagnosticsTab to diagnostics)) {
            tab.isSelected = selected
            styleButton(tab, if (selected) 0xffdbeafe.toInt() else 0xffe3ebf5.toInt(), if (selected) accent else muted)
        }
        scroll.scrollTo(0, 0)
    }

    private fun render() {
        val snapshot = CollectorService.uiSnapshot
        val running = CollectorService.running
        if (snapshot.manualActive || snapshot.activeRun != null || (!manualMode && snapshot.listening)) requestingService = false
        if (snapshot.manualActive) manualMode = true
        if (snapshot.activeRun != null) manualMode = false
        val display = if (manualMode && !snapshot.manualActive) CollectorDisplay(lastError = snapshot.lastError) else snapshot
        val locked = display.manualActive || display.activeRun != null || requestingService
        manualModeButton.isEnabled = !locked
        autoModeButton.isEnabled = !locked
        styleButton(manualModeButton, if (manualMode) accent else 0xffe3ebf5.toInt(), if (manualMode) Color.WHITE else ink)
        styleButton(autoModeButton, if (!manualMode) accent else 0xffe3ebf5.toInt(), if (!manualMode) Color.WHITE else ink)
        val fine = hasFineLocation()
        val gps = getSystemService(LocationManager::class.java)?.isProviderEnabled(LocationManager.GPS_PROVIDER) == true
        phase.show(when {
            requestingService -> "正在启动采集服务"
            manualMode -> if (display.manualActive) "独立采集中" else "独立采集未启动"
            running && !display.listening -> "USB 服务未就绪"
            else -> display.phase()
        })
        connection.show(when {
            !fine -> "请授予精确定位权限"
            !gps -> "请打开系统定位"
            manualMode -> "独立模式无需 USB 或上位机"
            display.connected -> "USB ADB 已连接 · TCP 18765"
            display.listening -> "等待 Windows 上位机连接 · TCP 18765"
            else -> "打开系统定位后启动 USB 采集"
        })
        start.show(if (manualMode) "开始采集" else "启动 USB 通信")
        stop.show(if (manualMode) "停止采集" else "结束自动化测试")
        start.isEnabled = !requestingService && if (manualMode) !display.manualActive && display.activeRun == null else !display.listening
        stop.isEnabled = running && if (manualMode) display.manualActive else display.activeRun != null
        val trial = display.activeAttempt ?: display.preparedAttempt ?: display.latestAttempt
        identifiers.visibility = if (manualMode) View.GONE else View.VISIBLE
        identifiers.show("运行 ${display.activeRun ?: "—"}\n试验 ${trial ?: "—"}")
        ttff.show(format(display.ttff, 3, " s"))
        accuracyLabel.show(if (manualMode) "定位精度" else "水平误差")
        error.show(format(if (manualMode) display.manualAccuracyM else display.errorM, 2, " m"))
        used.show(display.usedInFix?.toString() ?: "—")
        coordinates.show("纬度 ${format(display.latitude, 6, "°")}   经度 ${format(display.longitude, 6, "°")}")
        livePosition.show(if (manualMode && !display.manualActive) "等待开始独立采集" else if (display.liveLatitude == null || display.liveLongitude == null)
            "本轮尚无新定位 · 不显示上一轮坐标" else
            "最新纬度 ${format(display.liveLatitude, 6, "°")}  经度 ${format(display.liveLongitude, 6, "°")}\n" +
            (if (manualMode) "定位精度 ${format(display.manualAccuracyM, 2, " m")} · 新定位 ${display.liveFixCount} 条" else
            "实时误差 ${format(display.liveErrorM, 2, " m")} · 新定位 ${display.liveFixCount} 条 · 回调延迟 ${display.liveAgeMs ?: 0} ms"))
        result.show(when {
            manualMode -> if (display.manualActive) "持续采集 · TTFF 仅供调试参考" else "等待独立采集"
            display.activeAttempt != null -> "正在等待本轮结果"
            display.result == "OBSERVED" -> "首次定位已采集 · 待上位机判定"
            display.reason == "TIMEOUT" -> "观察窗口内未定位"
            display.result == "INVALID" -> "本轮无效 · ${readableReason(display.reason)}"
            else -> "等待试验"
        })
        satellites.show(if (display.satellites.isEmpty()) "等待卫星遥测" else {
            val strongest = display.satellites.sortedByDescending { it.cn0 }
            val unique = strongest.groupBy { it.constellation to it.svid }.values
            fun flag(value: Boolean?) = when (value) { true -> "有"; false -> "无"; null -> "未知" }
            "可见 ${unique.size} 颗 · 参与解算 ${unique.count { group -> group.any { it.used } }} 颗\n" +
                "有星历 ${unique.count { group -> group.any { it.ephemeris == true } }} 颗 · 有历书 ${unique.count { group -> group.any { it.almanac == true } }} 颗\n" +
                strongest.joinToString("\n") {
                    "${constellation(it.constellation)} ${it.svid}    ${format(it.cn0, 1, " dB-Hz")}" +
                        "    星历:${flag(it.ephemeris)} 历书:${flag(it.almanac)}" +
                        (if (it.used) "    已解算" else "    未解算")
                }
        })
        systemChecks.show("${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE}\n" +
            "精确定位  ${if (fine) "已授权" else "未授权"}\n系统定位  ${if (gps) "已开启" else "已关闭"}")
        records.show("已写入 ${display.recordCount} 条事件\n最近异常  ${readableReason(display.lastError)}")
        rootStatus.show(if (probing) "正在检测 Root…" else CollectorService.rootEvidence)
        probe.isEnabled = !probing
    }

    override fun onStart() { super.onStart(); ui.post(update) }
    override fun onStop() { ui.removeCallbacks(update); super.onStop() }

    private fun hasFineLocation() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun requestCollector() {
        if (getSystemService(LocationManager::class.java)?.isProviderEnabled(LocationManager.GPS_PROVIDER) != true) {
            Toast.makeText(this, "请先开启系统定位", Toast.LENGTH_LONG).show()
            return
        }
        if (hasFineLocation()) startCollector()
        else requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION), 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 1) return
        if (hasFineLocation()) startCollector()
        else Toast.makeText(this, "需要精确定位权限", Toast.LENGTH_LONG).show()
    }

    private fun startCollector() {
        try {
            startForegroundService(Intent(this, CollectorService::class.java).setAction(if (manualMode) "START_MANUAL" else "START_USB"))
            requestingService = true
            ui.postDelayed({ requestingService = false }, 4000)
            render()
        } catch (error: IllegalStateException) {
            Toast.makeText(this, "请在 Android APP 界面启动采集服务", Toast.LENGTH_LONG).show()
            return
        } catch (error: SecurityException) {
            Toast.makeText(this, "无法启动定位服务，请检查精确定位权限", Toast.LENGTH_LONG).show()
            return
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        }
    }

    private fun probeRoot() {
        CollectorService.rootEvidence = runCatching {
            val process = ProcessBuilder("su", "-c", "id").redirectErrorStream(true).start()
            try {
                if (!process.waitFor(5, TimeUnit.SECONDS)) "su -c id: timeout"
                else "su -c id: exit=${process.exitValue()}, ${process.inputStream.readBytes().decodeToString().trim()}"
            } finally {
                process.destroyForcibly()
            }
        }.getOrElse { "su -c id: ${it.message}" }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + 0.5f).toInt()

    private fun TextView.show(value: String) {
        if (text.toString() != value) text = value
    }

    private fun text(value: String, size: Int, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = value
        textSize = size.toFloat()
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun column(spacing: Int = 0) = object : LinearLayout(this) {
        init { orientation = VERTICAL }
        override fun addView(child: View) {
            val params = LayoutParams(-1, -2)
            if (childCount > 0) params.topMargin = dp(spacing)
            super.addView(child, params)
        }
    }

    private fun page() = column(10).apply { setPadding(dp(16), dp(4), dp(16), dp(18)) }

    private fun card(title: String) = column(8).apply {
        background = GradientDrawable().apply {
            setColor(Color.WHITE)
            setStroke(dp(1), 0xffd6e0eb.toInt())
            cornerRadius = dp(12).toFloat()
        }
        setPadding(dp(14), dp(12), dp(14), dp(12))
        addView(text(title, 15, ink, true))
    }

    private fun action(value: String, run: () -> Unit) = Button(this).apply {
        text = value
        isAllCaps = false
        minHeight = dp(48)
        setOnClickListener { run() }
        styleButton(this, 0xffe3ebf5.toInt(), accent)
    }

    private fun styleButton(button: Button, fill: Int, foreground: Int) {
        val states = arrayOf(intArrayOf(-android.R.attr.state_enabled), intArrayOf())
        button.backgroundTintList = ColorStateList(states, intArrayOf(0xffe7edf4.toInt(), fill))
        button.setTextColor(ColorStateList(states, intArrayOf(muted, foreground)))
    }

    private fun weighted() = LinearLayout.LayoutParams(0, -2, 1f)

    private fun metric(parent: LinearLayout, title: String): TextView {
        val block = column(3)
        block.addView(text(title, 12, muted))
        val value = text("—", 19, ink, true)
        block.addView(value)
        parent.addView(block, weighted())
        return value
    }

    private fun format(value: Double?, digits: Int, unit: String) =
        value?.let { String.format(Locale.ROOT, "%.${digits}f", it) + unit } ?: "—"

    private fun readableReason(reason: String?) = when (reason) {
        "USER_STOP" -> "操作员停止"
        "TRANSPORT_ERROR" -> "USB 通信中断"
        "INVALID_TELEMETRY" -> "卫星关联证据不足"
        "GNSS_NOT_READY", "GPS_DISABLED" -> "定位服务不可用"
        "GNSS_STOPPED" -> "接收机已停止"
        "SERVICE_STOP" -> "采集服务已停止"
        null -> "—"
        else -> reason
    }

    private fun constellation(type: Int) = when (type) {
        1 -> "GPS"
        2 -> "SBAS"
        3 -> "GLONASS"
        4 -> "QZSS"
        5 -> "北斗"
        6 -> "Galileo"
        7 -> "NavIC"
        else -> "其他"
    }
}
