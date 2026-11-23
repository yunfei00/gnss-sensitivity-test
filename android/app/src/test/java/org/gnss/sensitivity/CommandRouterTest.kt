package org.gnss.sensitivity

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CommandRouterTest {
    private class MemoryJournal : Journal {
        val commands = mutableMapOf<String, Pair<String, String>>()
        val events = mutableListOf<JSONObject>()
        var acked = 0L
        override fun append(event: JSONObject) { events.add(event.put("seq", events.size + 1)) }
        override fun fetch(run: String, after: Long) = JSONArray(events.filter {
            it.getString("run_id") == run && it.getLong("seq") > after
        })
        override fun ack(run: String, seq: Long) { acked = maxOf(seq, acked) }
        override fun count() = events.size.toLong()
        override fun claim(id: String, request: String): String? {
            val previous = commands[id]
            if (previous != null) {
                require(previous.first == request)
                return previous.second
            }
            commands[id] = request to ""
            return null
        }
        override fun complete(id: String, response: String) {
            commands[id] = commands.getValue(id).first to response
        }
    }

    @Test fun duplicatedStartReturnsCachedReplyAcrossRouterInstances() {
        val journal = MemoryJournal()
        var starts = 0
        fun router() = CommandRouter(journal) {
            starts++
            JSONObject().put("ready", true)
        }
        val start = envelope("START_ATTEMPT", "run", "trial", JSONObject())
        val original = router().dispatch(start.toString())
        val replay = router().dispatch(start.toString())
        assertEquals("DEVICE_STATUS", original.getString("type"))
        assertEquals(original.toString(), replay.toString())
        assertEquals(1, starts)
        assertEquals("ERROR", router().dispatch(start.put("seq", 2).toString()).getString("type"))
        assertEquals(1, starts)
    }

    @Test fun responseContainsOnlyEventsAfterCommittedHostCursor() {
        val journal = MemoryJournal()
        val router = CommandRouter(journal) { JSONObject() }
        journal.append(envelope("ATTEMPT_RESULT", "run", "first", JSONObject()))
        journal.append(envelope("ATTEMPT_RESULT", "other", "first", JSONObject()))
        journal.append(envelope("ATTEMPT_RESULT", "run", "second", JSONObject()))
        val ack = envelope("ACK", "run", null, JSONObject().put("seq", 1))
        router.dispatch(ack.toString())
        router.dispatch(ack.toString())
        val fetch = envelope("FETCH_EVENTS", "run", null, JSONObject().put("last_ack_seq", 1))
        val events = router.dispatch(fetch.toString()).getJSONObject("payload").getJSONArray("events")
        assertEquals(1L, journal.acked)
        assertEquals(1, events.length())
        assertEquals(3, events.getJSONObject(0).getInt("seq"))
    }

    @Test fun rejectsDifferentVersionAndInterruptedCommand() {
        val journal = MemoryJournal()
        val router = CommandRouter(journal) { error("Must not execute") }
        val hello = envelope("HELLO", "run", null, JSONObject()).put("protocol_version", 2)
        assertEquals("ERROR", router.dispatch(hello.toString()).getString("type"))
        val start = envelope("START_ATTEMPT", "run", "trial", JSONObject())
        journal.claim(start.getString("message_id"), start.toString())
        assertEquals("ERROR", router.dispatch(start.toString()).getString("type"))
    }
}
