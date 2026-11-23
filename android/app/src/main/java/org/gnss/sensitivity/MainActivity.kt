package org.gnss.sensitivity

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowInsets
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.util.concurrent.TimeUnit

class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var details: TextView
    private val update = object : Runnable {
        override fun run() {
            details.text = "${CollectorService.rootEvidence}\n${CollectorService.diagnosticsText}"
            ui.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        val padding = (16 * resources.displayMetrics.density).toInt()
        content.setPadding(padding, padding, padding, padding)
        if (Build.VERSION.SDK_INT >= 35) {
            content.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(padding + bars.left, padding + bars.top,
                    padding + bars.right, padding + bars.bottom)
                insets
            }
        }
        fun button(label: String, action: () -> Unit) {
            content.addView(Button(this).apply { text = label; setOnClickListener { action() } })
        }
        button("授权并启动 USB 采集") {
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) startCollector()
            else requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION), 1)
        }
        button("停止当前测试") {
            if (CollectorService.running) {
                startService(Intent(this, CollectorService::class.java).setAction("STOP"))
            } else {
                Toast.makeText(this, "采集服务未启动", Toast.LENGTH_SHORT).show()
            }
        }
        button("检测 Root（su -c id）") { Thread(::probeRoot, "root-diagnostics").start() }
        details = TextView(this)
        content.addView(details)
        setContentView(ScrollView(this).apply { addView(content) })
    }

    override fun onStart() { super.onStart(); ui.post(update) }
    override fun onStop() { ui.removeCallbacks(update); super.onStop() }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            startCollector()
        } else if (requestCode == 1) Toast.makeText(this, "需要精确定位权限", Toast.LENGTH_LONG).show()
    }

    private fun startCollector() {
        try {
            startForegroundService(Intent(this, CollectorService::class.java))
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
}
