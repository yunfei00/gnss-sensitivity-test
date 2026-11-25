package org.gnss.sensitivity

import org.json.JSONObject

class CommandRouter(private val journal: Journal, private val control: (JSONObject) -> JSONObject) {
    fun dispatch(raw: String): JSONObject {
        val command = JSONObject(raw)
        val run = command.optString("run_id", "invalid")
        val attempt = command.takeUnless { it.isNull("attempt_id") }?.optString("attempt_id")
        val id = command.optString("message_id")
        fun reply(type: String, payload: JSONObject): JSONObject =
            envelope(type, run, attempt, payload.put("response_to", id))

        return try {
            validateCommand(command)
            val args = command.getJSONObject("payload")
            when (command.getString("type")) {
                "FETCH_EVENTS" -> reply("DEVICE_STATUS", JSONObject().put("events",
                    journal.fetch(run, cursor(args, "last_ack_seq"))))
                "ACK" -> {
                    journal.ack(run, cursor(args, "seq"))
                    reply("DEVICE_STATUS", JSONObject())
                }
                "GET_STATUS", "HELLO", "PING" -> reply("DEVICE_STATUS", control(command))
                else -> {
                    val cached = journal.claim(id, raw)
                    if (cached != null) {
                        require(cached.isNotEmpty()) { "Previous command interrupted; verify device state" }
                        return JSONObject(cached)
                    }
                    val response = try {
                        reply("DEVICE_STATUS", control(command))
                    } catch (error: Exception) {
                        reply("ERROR", JSONObject().put("reason", error.message ?: "DEVICE_ERROR"))
                    }
                    journal.complete(id, response.toString())
                    response
                }
            }
        } catch (error: Exception) {
            reply("ERROR", JSONObject().put("reason", error.message ?: "DEVICE_ERROR"))
        }
    }

    private fun cursor(args: JSONObject, key: String): Long {
        val value = args.get(key)
        require((value is Int || value is Long) && (value as Number).toLong() >= 0) { "Invalid cursor" }
        return (value as Number).toLong()
    }
}
