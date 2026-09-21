package com.pendulumapp

import android.content.Context
import org.json.JSONObject

/**
 * A loaded video's per-frame recorded floor-edge angle, exported offline by
 * python/export_angle_track.py (see that script's docstring for the sign convention:
 * angleDeg here is unnegated, matching python/pendulum_sim.py's `real_here` -- callers
 * apply the compensating negation themselves, same as pendulum_sim.py does).
 *
 * [lookup] mirrors pendulum_sim.py's `angle_filled[i] + frac*(angle_filled[i+1]-angle_filled[i])`
 * and its `local_slope`, but indexed by position in milliseconds (as MediaPlayer.currentPosition
 * reports) rather than by frame index, and with the slope expressed per second of video time
 * rather than per source frame.
 */
class AngleTimeline private constructor(
    private val tMs: IntArray,
    private val angleDeg: FloatArray,
    val fps: Double,
    val durationMs: Int
) {
    data class Sample(val realHere: Double, val localSlopePerSec: Double)

    /** Returns null only if the timeline has fewer than 2 samples (unusable). */
    fun lookup(posMs: Int): Sample? {
        if (tMs.size < 2) return null

        val clamped = posMs.coerceIn(tMs.first(), tMs.last())
        var i = tMs.binarySearch(clamped)
        if (i < 0) i = (-i - 2).coerceAtLeast(0)   // insertion point -> preceding sample index
        if (i >= tMs.size - 1) i = tMs.size - 2

        val t0 = tMs[i]
        val t1 = tMs[i + 1]
        val a0 = angleDeg[i].toDouble()
        val a1 = angleDeg[i + 1].toDouble()
        val spanMs = (t1 - t0).coerceAtLeast(1)
        val frac = (clamped - t0).toDouble() / spanMs

        val realHere = a0 + frac * (a1 - a0)
        val localSlopePerSec = (a1 - a0) * 1000.0 / spanMs
        return Sample(realHere, localSlopePerSec)
    }

    companion object {
        /** Plain-data factory, no Android Context required -- for unit tests and any other
         * caller that already has the timeline arrays in hand. */
        fun fromArrays(tMs: IntArray, angleDeg: FloatArray, fps: Double, durationMs: Int): AngleTimeline {
            require(tMs.size == angleDeg.size) { "tMs/angleDeg length mismatch" }
            return AngleTimeline(tMs, angleDeg, fps, durationMs)
        }

        /** Loads a timeline exported by python/export_angle_track.py from an Android asset. */
        fun loadFromAsset(context: Context, assetPath: String): AngleTimeline {
            val json = context.assets.open(assetPath).bufferedReader().use { it.readText() }
            val obj = JSONObject(json)

            val tArr = obj.getJSONArray("tMs")
            val aArr = obj.getJSONArray("angleDeg")
            require(tArr.length() == aArr.length()) { "tMs/angleDeg length mismatch in $assetPath" }

            val tMs = IntArray(tArr.length()) { tArr.getInt(it) }
            val angleDeg = FloatArray(aArr.length()) { aArr.getDouble(it).toFloat() }

            return fromArrays(tMs, angleDeg, obj.getDouble("fps"), obj.getInt("durationMs"))
        }
    }
}
