package org.gnss.sensitivity

import android.Manifest
import android.content.Intent
import android.location.LocationManager
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CollectorLifecycleTest {
    private fun awaitState(predicate: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 15000
        while (!predicate() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(100)
        assertTrue("Collector state did not converge", predicate())
    }

    @Test fun manualStartStopWithoutHost() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.ACCESS_COARSE_LOCATION)
        instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.ACCESS_FINE_LOCATION)
        val gps = context.getSystemService(LocationManager::class.java)
        assertTrue("Emulator GPS must be enabled", gps.isProviderEnabled(LocationManager.GPS_PROVIDER))
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        try {
            instrumentation.runOnMainSync {
                activity.startForegroundService(Intent(context, CollectorService::class.java).setAction("START_MANUAL"))
            }
            awaitState { CollectorService.uiSnapshot.manualActive }
            assertFalse(CollectorService.uiSnapshot.connected)
            assertNull(CollectorService.uiSnapshot.activeAttempt)
            instrumentation.runOnMainSync {
                activity.startService(Intent(context, CollectorService::class.java).setAction("STOP_MANUAL"))
            }
            awaitState { !CollectorService.uiSnapshot.manualActive }
        } finally {
            instrumentation.runOnMainSync {
                activity.stopService(Intent(context, CollectorService::class.java))
                activity.finish()
            }
            awaitState { !CollectorService.running }
        }
    }
}
