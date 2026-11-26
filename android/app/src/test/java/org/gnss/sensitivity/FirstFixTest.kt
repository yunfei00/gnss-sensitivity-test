package org.gnss.sensitivity

import org.junit.Assert.*
import org.junit.Test

class FirstFixTest {
    @Test fun ignoresStaleFutureWrongProviderMockAndInvalidCoordinates() {
        val selector = FirstFix(100, 500)
        val valid = Fix(150, 0.0, 0.0)
        assertFalse(selector.accept(valid.copy(atNs = 100), "gps", false, 150))
        assertFalse(selector.accept(valid, "gps", false, 149))
        assertFalse(selector.accept(valid.copy(atNs = 601), "gps", false, 601))
        assertFalse(selector.accept(valid, "network", false, 150))
        assertFalse(selector.accept(valid, "gps", true, 150))
        assertFalse(selector.accept(valid.copy(latitude = Double.NaN), "gps", false, 150))
        assertTrue(selector.accept(valid, "gps", false, 150))
        assertFalse(selector.accept(Fix(160, 1.0, 1.0), "gps", false, 160))
        assertEquals(valid, selector.fix)
    }

    @Test fun acceptsFirstPostFixCallbackWithinTolerance() {
        val selector = FirstFix(100, 500)
        selector.accept(Fix(150, 0.0, 0.0), "gps", false, 152)
        val before = SatelliteSnapshot(140, setOf(1 to 2, 1 to 3))
        val after = before.copy(receivedNs = 155)
        assertNull(selector.associate(listOf(before), 20))
        assertEquals(after, selector.associate(listOf(before, after), 9))
        assertEquals(after.copy(used = setOf(1 to 2, 1 to 8)),
            selector.associate(listOf(before, after.copy(used = setOf(1 to 2, 1 to 8))), 20))
        assertEquals(after, selector.associate(listOf(before, after), 20))
        assertNull(selector.associate(listOf(before), 20))
        assertNull(selector.associate(listOf(SatelliteSnapshot(171, emptySet())), 20))
    }

    @Test fun zeroUsedSatellitesAreInvalidTelemetry() {
        val selector = FirstFix(100, 500)
        selector.accept(Fix(150, 0.0, 0.0), "gps", false, 152)
        val a = SatelliteSnapshot(140, emptySet())
        val b = SatelliteSnapshot(155, emptySet())
        assertNull(selector.associate(listOf(a, b), 20))
        val used = SatelliteSnapshot(160, setOf(1 to 2))
        assertEquals(used, selector.associate(listOf(a, b, used), 20))
    }

    @Test fun provisionalFixDoesNotEndAttemptAndLaterSatelliteFixWins() {
        val selector = SatelliteConfirmedFix(100, 500, 20)
        selector.offer(Fix(150, 0.0, 0.0), "gps", false, 152)
        assertNull(selector.confirm(SatelliteSnapshot(155, emptySet())))
        assertNull(selector.fix)
        assertNull(selector.confirm(SatelliteSnapshot(160, setOf(1 to 2))))
        val actual = Fix(170, 1.0, 1.0)
        selector.offer(actual, "gps", false, 172)
        assertNull(selector.confirm(SatelliteSnapshot(175, setOf(1 to 2))))
        assertEquals(actual, selector.firstSatelliteFix)
        assertNull(selector.fix)
        val qualified = Fix(180, 1.0, 1.0)
        selector.offer(qualified, "gps", false, 182)
        assertEquals(qualified, selector.confirm(SatelliteSnapshot(185, setOf(1 to 2, 1 to 3, 1 to 4, 1 to 5))))
        assertEquals(qualified, selector.fix)
    }

    @Test fun expiredOrMissingSatelliteEvidenceDoesNotConfirmFix() {
        val selector = SatelliteConfirmedFix(100, 500, 20)
        selector.offer(Fix(150, 0.0, 0.0), "gps", false, 152)
        assertNull(selector.confirm(SatelliteSnapshot(171, setOf(1 to 2))))
        assertNull(selector.fix)
        selector.offer(Fix(601, 0.0, 0.0), "gps", false, 601)
        assertNull(selector.confirm(SatelliteSnapshot(602, setOf(1 to 2))))
        assertNull(selector.fix)
    }
}
