package com.pendulumapp

import kotlin.math.abs

/**
 * Ported control law from python/pendulum_sim.py's main loop (see
 * python/pendulum_sim_process.md sections 4 and 9 for the full rationale) -- a
 * feedforward + PID controller that continuously retimes video playback speed so the
 * video's own recorded floor-edge angle, at whatever position is currently playing,
 * stays the *opposite* of the pendulum's live physical angle. When the screen's physical
 * rotation and the video's baked-in tilt combine, they cancel.
 *
 * The Python version runs once per rendered video frame, offline, with a fixed dt=1/fps
 * and a formula-driven "ideal pendulum" standing in for the real one. This version runs
 * as a periodic real-time tick (see [tick], driven by a Handler loop in MainActivity),
 * with dt measured from wall-clock time and the live pendulum angle coming from a real
 * sensor ([PendulumTiltSensor]) instead of a formula.
 *
 * Dependencies are taken as plain lambdas/values rather than concrete Android types
 * (MediaPlayer, PendulumTiltSensor) so the control math itself -- the part that matters
 * to get right, and the part with a documented history of subtle bugs on the Python side
 * (see process doc section 6) -- can be unit-tested with fakes, without an emulator.
 */
class PendulumSpeedController(
    private val timeline: AngleTimeline,
    private val getLiveAngleDeg: () -> Float,
    private val getLiveAngularVelocityDegPerSec: () -> Float,
    private val hasLiveAngle: () -> Boolean,
    private val getVideoPositionMs: () -> Int,
    private val applySpeed: (Float) -> Unit,
    private val onTick: ((TickInfo) -> Unit)? = null,
    private val nowNanos: () -> Long = { System.nanoTime() },
    // PID gains and limits default to the production tuning, but are constructor
    // parameters (not read directly from PendulumTuning inside tick()) so tests can
    // compare configurations -- e.g. Kp-only vs Kp+Ki -- without touching global state.
    private val kp: Float = PendulumTuning.KP,
    private val ki: Float = PendulumTuning.KI,
    private val kd: Float = PendulumTuning.KD,
    private val iLimit: Double = PendulumTuning.I_LIMIT,
    private val minRate: Float = PendulumTuning.MIN_RATE,
    private val maxRate: Float = PendulumTuning.MAX_RATE,
    private val maxAccelPerFrame: Double = PendulumTuning.MAX_ACCEL_PER_FRAME,
    private val minSlopeDegPerFrame: Double = PendulumTuning.MIN_SLOPE_DEG_PER_FRAME,
    private val tickIntervalMs: Long = PendulumTuning.TICK_INTERVAL_MS
) {
    /** Snapshot of one tick's internals, for the optional debug readout. */
    data class TickInfo(
        val liveAngleDeg: Float,
        val rate: Float,
        val error: Double?,
        val realHere: Double?
    )

    // Python's MAX_ACCEL/MIN_SLOPE_DEG are expressed per source-*frame*; re-derive them
    // per *second* here using the loaded video's actual fps, since this loop runs on a
    // real-time timer, not a frame loop.
    private val maxAccelPerSec = maxAccelPerFrame * timeline.fps
    private val minSlopeDegPerSec = minSlopeDegPerFrame * timeline.fps

    private var rate = 1.0f
    private var integralError = 0.0
    private var prevError: Double? = null
    private var lastTickNanos = 0L

    /** Call when (re)starting playback from a known position (e.g. Start, or a loop restart)
     * so stale integral/derivative state doesn't leak across the boundary. */
    fun reset() {
        rate = 1.0f
        integralError = 0.0
        prevError = null
        lastTickNanos = 0L
    }

    fun tick() {
        val now = nowNanos()
        var dt = if (lastTickNanos == 0L) {
            tickIntervalMs / 1000.0
        } else {
            (now - lastTickNanos) / 1_000_000_000.0
        }
        lastTickNanos = now

        // A stale/huge gap (app backgrounded, GC pause, first tick after resume) makes
        // accumulated integral/derivative state meaningless -- treat it like a fresh start
        // rather than feeding a bogus dt into the correction.
        if (dt > 0.5 || dt <= 0.0) {
            integralError = 0.0
            prevError = null
            dt = tickIntervalMs / 1000.0
        }

        val desiredRate: Double
        var error: Double? = null
        var realHere: Double? = null

        val sample = if (hasLiveAngle()) timeline.lookup(getVideoPositionMs()) else null

        if (sample == null || abs(sample.localSlopePerSec) < minSlopeDegPerSec) {
            // No reliable local direction to steer by (flat/gap region, or no sensor
            // reading yet) -- coast at normal speed rather than winding up on stale data.
            integralError = 0.0
            prevError = null
            desiredRate = 1.0
        } else {
            val liveAngle = getLiveAngleDeg().toDouble()
            val liveAngularVelocity = getLiveAngularVelocityDegPerSec().toDouble()

            // The arm's rotation is applied on top of whatever tilt is already baked into
            // the video, so for the two to cancel (rather than double) the target is the
            // OPPOSITE of the live pendulum angle -- see process doc section 6.
            val targetDeg = -liveAngle
            val targetDeriv = -liveAngularVelocity

            realHere = sample.realHere
            val e = targetDeg - sample.realHere
            error = e

            integralError = (integralError + e * dt).coerceIn(-iLimit, iLimit)
            val derrorDt = if (prevError == null) 0.0 else (e - prevError!!) / dt
            prevError = e

            val desiredDRealDt = targetDeriv + kp * e + ki * integralError + kd * derrorDt
            desiredRate = desiredDRealDt / sample.localSlopePerSec
        }

        val maxStep = (maxAccelPerSec * dt).toFloat()
        rate += (desiredRate.toFloat() - rate).coerceIn(-maxStep, maxStep)
        rate = rate.coerceIn(minRate, maxRate)

        applySpeed(rate)
        onTick?.invoke(TickInfo(getLiveAngleDeg(), rate, error, realHere))
    }
}
