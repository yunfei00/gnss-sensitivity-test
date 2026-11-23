package org.gnss.sensitivity

import org.json.JSONObject
import java.io.InputStream
import java.io.IOException
import java.time.Instant
import java.util.UUID

const val MAX_LINE = 1024 * 1024
val commands = setOf("HELLO", "GET_STATUS", "CONFIGURE_RUN", "PREPARE_ATTEMPT",
    "START_ATTEMPT", "STOP_ATTEMPT", "STOP_RUN", "FETCH_EVENTS", "ACK", "PING")
val attemptCommands = setOf("PREPARE_ATTEMPT", "START_ATTEMPT", "STOP_ATTEMPT")

fun envelope(type: String, run: String, attempt: String?, payload: JSONObject, seq: Long = 0,
             monotonicNs: Long? = null): JSONObject =
    JSONObject().put("protocol_version", 1).put("type", type).put("run_id", run)
        .put("attempt_id", attempt ?: JSONObject.NULL).put("message_id", UUID.randomUUID().toString())
        .put("seq", seq).put("utc_timestamp", Instant.now().toString()).put("payload", payload)
        .also { if (monotonicNs != null) it.put("monotonic_ns", monotonicNs) }

fun validateCommand(command: JSONObject) {
    require(command.get("protocol_version") == 1) { "Unsupported protocol version" }
    val type = command.get("type") as? String
    require(type in commands) { "Unknown command" }
    for (key in listOf("run_id", "message_id")) {
        val value = command.get(key)
        require(value is String && value.length in 1..128) { "Invalid $key" }
    }
    val attempt = command.get("attempt_id")
    require((attempt == JSONObject.NULL && type !in attemptCommands) ||
        (attempt is String && attempt.length in 1..128)) { "Invalid attempt_id" }
    val seq = command.get("seq")
    require((seq is Int || seq is Long) && (seq as Number).toLong() >= 0) { "Invalid seq" }
    if (command.has("monotonic_ns")) {
        val time = command.get("monotonic_ns")
        require((time is Int || time is Long) && (time as Number).toLong() >= 0)
    }
    require(command.keys().asSequence().all { it in setOf("protocol_version", "type", "run_id",
        "attempt_id", "message_id", "seq", "utc_timestamp", "monotonic_ns", "payload") })
    Instant.parse(command.get("utc_timestamp") as String)
    command.getJSONObject("payload")
}

fun InputStream.readFrame(): String? {
    val buffer = java.io.ByteArrayOutputStream()
    while (buffer.size() < MAX_LINE) {
        when (val byte = read()) {
            -1 -> return if (buffer.size() == 0) null else throw IOException("Incomplete frame")
            10 -> return Charsets.UTF_8.newDecoder().decode(java.nio.ByteBuffer.wrap(buffer.toByteArray())).toString()
            else -> buffer.write(byte)
        }
    }
    throw IOException("Frame too large")
}
