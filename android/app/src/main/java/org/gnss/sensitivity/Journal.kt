package org.gnss.sensitivity

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject

interface Journal {
    fun append(event: JSONObject)
    fun fetch(run: String, after: Long): JSONArray
    fun ack(run: String, seq: Long)
    fun count(): Long
    fun claim(id: String, request: String): String?
    fun complete(id: String, response: String)
}

class SQLiteJournal(context: Context) : SQLiteOpenHelper(context, "gnss-events.db", null, 2), Journal {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, body TEXT NOT NULL)")
        db.execSQL("CREATE INDEX events_run_seq ON events(run, seq)")
        db.execSQL("CREATE TABLE commands(id TEXT PRIMARY KEY, request TEXT NOT NULL, reply TEXT NOT NULL)")
        db.execSQL("CREATE TABLE cursors(run TEXT PRIMARY KEY, seq INTEGER NOT NULL)")
        createManualTable(db)
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion == 1 && newVersion == 2) createManualTable(db)
        else error("Unsupported journal migration $oldVersion -> $newVersion")
    }

    private fun createManualTable(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE manual_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, kind TEXT NOT NULL, wall_ms INTEGER NOT NULL, monotonic_ns INTEGER NOT NULL, body TEXT NOT NULL)")
        db.execSQL("CREATE INDEX manual_session_seq ON manual_events(session, seq)")
    }

    fun appendManual(session: String, kind: String, body: JSONObject) {
        writableDatabase.insertOrThrow("manual_events", null, ContentValues().apply {
            put("session", session)
            put("kind", kind)
            put("wall_ms", System.currentTimeMillis())
            put("monotonic_ns", android.os.SystemClock.elapsedRealtimeNanos())
            put("body", body.toString())
        })
    }

    fun manualCount(): Long = readableDatabase.rawQuery("SELECT count(*) FROM manual_events", null)
        .use { cursor -> cursor.moveToFirst(); cursor.getLong(0) }

    override fun append(event: JSONObject) {
        writableDatabase.insertOrThrow("events", null, ContentValues().apply {
            put("run", event.getString("run_id"))
            put("body", event.toString())
        })
    }

    override fun fetch(run: String, after: Long): JSONArray {
        val events = JSONArray()
        readableDatabase.rawQuery(
            "SELECT seq, body FROM events WHERE run=? AND seq>? ORDER BY seq LIMIT 24",
            arrayOf(run, after.toString())
        ).use { cursor ->
            while (cursor.moveToNext()) {
                events.put(JSONObject(cursor.getString(1)).put("seq", cursor.getLong(0)))
            }
        }
        return events
    }

    override fun ack(run: String, seq: Long) {
        writableDatabase.execSQL("INSERT OR IGNORE INTO cursors(run, seq) VALUES(?, ?)", arrayOf(run, seq))
        writableDatabase.execSQL("UPDATE cursors SET seq=? WHERE run=? AND seq<?", arrayOf(seq, run, seq))
    }

    override fun count(): Long = readableDatabase.rawQuery("SELECT count(*) FROM events", null)
        .use { cursor -> cursor.moveToFirst(); cursor.getLong(0) }

    override fun claim(id: String, request: String): String? {
        readableDatabase.rawQuery("SELECT request, reply FROM commands WHERE id=?", arrayOf(id)).use { cursor ->
            if (cursor.moveToFirst()) {
                require(cursor.getString(0) == request) { "Command ID reused with different data" }
                return cursor.getString(1)
            }
        }
        writableDatabase.insertOrThrow("commands", null, ContentValues().apply {
            put("id", id)
            put("request", request)
            put("reply", "")
        })
        return null
    }

    override fun complete(id: String, response: String) {
        writableDatabase.execSQL("UPDATE commands SET reply=? WHERE id=?", arrayOf(response, id))
    }
}
