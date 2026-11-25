package org.gnss.sensitivity

import org.junit.Assert.assertEquals
import org.junit.Test

class CollectorDisplayTest {
    @Test fun identifiesIdleAndConnectedService() {
        val idle = CollectorDisplay()
        assertEquals("采集服务未启动", idle.phase())
        assertEquals("等待 USB ADB 连接", idle.copy(listening = true).phase())
        assertEquals("上位机已连接", idle.copy(listening = true, connected = true).phase())
    }

    @Test fun activeAttemptTakesPrecedenceOverPreparedAndConnected() {
        val prepared = CollectorDisplay(listening = true, connected = true, preparedAttempt = "pending")
        assertEquals("等待上位机开始", prepared.phase())
        assertEquals("正在采集", prepared.copy(activeAttempt = "active").phase())
    }
    @Test fun manualCollectionDoesNotDependOnUsb() {
        val manual = CollectorDisplay(manualActive = true, manualAccuracyM = 4.0)
        assertEquals("独立采集中", manual.phase())
        assertEquals("独立采集中", manual.copy(listening = true, connected = true).phase())
        assertEquals("独立采集中", manual.copy(listening = false, connected = false).phase())
        assertEquals(null, manual.errorM)
        assertEquals(4.0, manual.manualAccuracyM!!, 0.0)
    }

    @Test fun manualStopReturnsToIdle() {
        val manual = CollectorDisplay(manualActive = true)
        assertEquals("采集服务未启动", manual.copy(manualActive = false).phase())
    }
}
