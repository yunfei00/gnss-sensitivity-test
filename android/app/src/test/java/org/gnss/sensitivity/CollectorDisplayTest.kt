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
}
