package org.gnss.sensitivity

import android.content.Context
import android.content.ContextWrapper
import android.database.sqlite.SQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class JournalMigrationTest {
    @Test fun migratesAndPersistsWithoutMixingStreams() {
        val target = InstrumentationRegistry.getInstrumentation().targetContext
        val name = "test-" + UUID.randomUUID() + ".db"
        val context = object : ContextWrapper(target) {
            override fun openOrCreateDatabase(n: String, mode: Int, factory: SQLiteDatabase.CursorFactory?,
                errorHandler: android.database.DatabaseErrorHandler?): SQLiteDatabase =
                target.openOrCreateDatabase(name, mode, factory, errorHandler)
            override fun getDatabasePath(n: String) = target.getDatabasePath(name)
        }
        try {
            target.openOrCreateDatabase(name, Context.MODE_PRIVATE, null).use { db ->
                db.execSQL("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, body TEXT NOT NULL)")
                db.execSQL("CREATE INDEX events_run_seq ON events(run, seq)")
                db.execSQL("CREATE TABLE commands(id TEXT PRIMARY KEY, request TEXT NOT NULL, reply TEXT NOT NULL)")
                db.execSQL("CREATE TABLE cursors(run TEXT PRIMARY KEY, seq INTEGER NOT NULL)")
                db.execSQL("INSERT INTO events(run, body) VALUES(?, ?)", arrayOf("formal", JSONObject().put("run_id", "formal").toString()))
                db.version = 1
            }
            SQLiteJournal(context).use { journal ->
                assertEquals(1L, journal.count())
                assertEquals(0L, journal.manualCount())
                journal.appendManual("manual", "SESSION_START", JSONObject())
                journal.appendManual("manual", "LOCATION_UPDATE", JSONObject().put("latitude", 30.0))
                journal.appendManual("manual", "SESSION_STOP", JSONObject())
                assertEquals(1, journal.fetch("formal", 0).length())
                assertEquals(0, journal.fetch("manual", 0).length())
            }
            SQLiteJournal(context).use { journal ->
                assertEquals(3L, journal.manualCount())
                assertEquals(1L, journal.count())
                assertEquals(2, journal.readableDatabase.version)
            }
        } finally {
            target.deleteDatabase(name)
        }
    }
}
