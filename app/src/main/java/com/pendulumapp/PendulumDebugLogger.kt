package com.pendulumapp

import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileWriter

/**
 * Debug-only CSV logger pairing live sensor readings with the video's own recorded angle
 * at the same instant -- for offline analysis (e.g. in Python, alongside pendulum_sim.py's
 * own tooling) when the compensation isn't tracking correctly. Every field written mirrors
 * PendulumSpeedController.TickInfo, so a single tick's story -- what the sensor said, where
 * the video was, what the timeline said *there*, and what the controller decided -- is on
 * one row. Also logs the *raw* per-axis gravity/gyroscope values (PendulumTiltSensor's
 * gravityX/Y/Z, gyroX/Y/Z) alongside the derived angleDeg -- needed to calibrate
 * PendulumTiltSensor's `axis`/`invertSign` against real hardware: if the derived angle looks
 * wrong (e.g. huge/non-linear swings for a modest real motion), these raw columns show
 * which device axis is actually "down" at rest and which axis actually captures the swing,
 * rather than guessing again.
 *
 * Kept from growing unbounded three ways: a single fixed filename that's truncated fresh
 * each time tracking (re)starts (no accumulation across runs), a throttled write interval
 * (not every ~75ms control-loop tick), and a hard row cap as a backstop if left running a
 * long time. Only ever constructed/used from BuildConfig.DEBUG call sites in MainActivity.
 *
 * Pull the log with:
 *   adb pull /sdcard/Android/data/com.pendulumapp/files/pendulum_debug_log.csv
 */
class PendulumDebugLogger(context: Context) {

    companion object {
        private const val TAG = "PendulumApp"
        private const val FILE_NAME = "pendulum_debug_log.csv"
        private const val HEADER =
            "tMs,liveAngleDeg,liveAngularVelocityDegPerSec,videoPosMs,targetDeg," +
                "realHereDeg,localSlopeDegPerSec,errorDeg,rate," +
                "gravityX,gravityY,gravityZ,gyroX,gyroY,gyroZ\n"
        private const val WRITE_INTERVAL_MS = 200L
        private const val MAX_ROWS = 20_000 // ~1h6m of log at the 200ms write interval
    }

    private val file = File(context.getExternalFilesDir(null), FILE_NAME)

    private var startNanos = 0L
    private var lastWriteMs = 0L
    private var rowCount = 0
    private var capped = false

    /** Truncates any previous log and starts a fresh one. Call whenever tracking (re)starts
     * from IDLE, so each debugging run gets its own clean file instead of an ever-growing one. */
    fun start() {
        startNanos = System.nanoTime()
        lastWriteMs = -WRITE_INTERVAL_MS // write the very first tick immediately
        rowCount = 0
        capped = false
        try {
            file.writeText(HEADER)
            Log.i(TAG, "Debug log (re)started: ${file.absolutePath}")
        } catch (e: Exception) {
            // Storage unavailable -- logging is best-effort and must never block playback.
            Log.e(TAG, "Failed to (re)start debug log at ${file.absolutePath}", e)
        }
    }

    fun logTick(info: PendulumSpeedController.TickInfo, sensor: PendulumTiltSensor) {
        if (capped) return

        val nowMs = (System.nanoTime() - startNanos) / 1_000_000
        if (nowMs - lastWriteMs < WRITE_INTERVAL_MS) return
        lastWriteMs = nowMs

        if (rowCount >= MAX_ROWS) {
            capped = true
            return
        }
        rowCount++

        val row = buildString {
            append(nowMs).append(',')
            append(info.liveAngleDeg).append(',')
            append(info.liveAngularVelocityDegPerSec).append(',')
            append(info.videoPosMs).append(',')
            append(info.targetDeg).append(',')
            append(info.realHere ?: "").append(',')
            append(info.localSlopePerSec ?: "").append(',')
            append(info.error ?: "").append(',')
            append(info.rate).append(',')
            append(sensor.gravityX).append(',')
            append(sensor.gravityY).append(',')
            append(sensor.gravityZ).append(',')
            append(sensor.gyroX).append(',')
            append(sensor.gyroY).append(',')
            append(sensor.gyroZ).append('\n')
        }
        try {
            FileWriter(file, true).use { it.write(row) }
            if (rowCount == 1) Log.i(TAG, "Debug log: first row written OK to ${file.absolutePath}")
        } catch (e: Exception) {
            // Best-effort -- a dropped row shouldn't crash playback.
            Log.e(TAG, "Failed to write debug log row to ${file.absolutePath}", e)
        }
    }
}
