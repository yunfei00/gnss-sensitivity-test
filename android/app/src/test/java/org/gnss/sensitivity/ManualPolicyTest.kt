package org.gnss.sensitivity

import org.junit.Assert.*
import org.junit.Test

class ManualPolicyTest {
    @Test fun ownership() {
        for (ready in listOf(false, true))
            for (active in listOf(false, true))
                for (prepared in listOf(false, true))
                    for (configured in listOf(false, true))
                        assertEquals(ready && !active && !prepared && !configured,
                            ManualPolicy.canStart(ready, active, prepared, configured))
    }

    private fun fresh(provider: String? = "gps", mock: Boolean = false,
                      time: Long = 110, previous: Long = 0,
                      lat: Double = 30.0, lon: Double = 110.0) =
        ManualPolicy.fresh(provider, mock, time, 100, 200, previous, lat, lon)

    @Test fun rejectsCachedMockAndInvalidFixes() {
        assertFalse(fresh(time = 100))
        assertFalse(fresh(time = 99))
        assertFalse(fresh(time = 201))
        assertFalse(fresh(mock = true))
        assertFalse(fresh(provider = "network"))
        assertFalse(fresh(provider = null))
        assertFalse(fresh(previous = 110))
        assertFalse(fresh(previous = 111))
        assertFalse(fresh(lat = Double.NaN))
        assertFalse(fresh(lon = 181.0))
    }

    @Test fun acceptsSuccessiveFreshFixes() {
        assertTrue(fresh())
        assertTrue(fresh(time = 120, previous = 110))
        assertTrue(fresh(time = 200, previous = 120))
    }
}
