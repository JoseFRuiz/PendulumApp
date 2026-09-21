package com.pendulumapp

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Unit tests for the ported control law (see PendulumSpeedController's doc comment and
 * python/pendulum_sim_process.md sections 4/9). All dependencies are fakes -- a fake clock
 * (nowNanos) and fake live-angle/video-position suppliers -- so these run as plain JVM tests,
 * no emulator/Android framework needed.
 */
class PendulumSpeedControllerTest {

    private fun buildSineTimeline(amplitudeDeg: Double, periodSec: Double, fps: Double, durationSec: Double): AngleTimeline {
        val n = (durationSec * fps).toInt() + 1
        val tMs = IntArray(n) { (it * 1000.0 / fps).toInt() }
        val angleDeg = FloatArray(n) { i ->
            val t = tMs[i] / 1000.0
            (amplitudeDeg * sin(2 * PI * t / periodSec)).toFloat()
        }
        return AngleTimeline.fromArrays(tMs, angleDeg, fps, tMs.last())
    }

    @Test
    fun flatTimelineCausesControllerToCoastAtNormalSpeed() {
        // If the recorded video has no local direction to steer by (a flat/gap span),
        // the controller must fall back to 1x rather than acting on a meaningless slope.
        val flatTimeline = AngleTimeline.fromArrays(
            tMs = intArrayOf(0, 1000, 2000),
            angleDeg = floatArrayOf(5f, 5f, 5f),
            fps = 30.0,
            durationMs = 2000
        )
        var fakeNanos = 0L
        var appliedRate = -1f
        val controller = PendulumSpeedController(
            timeline = flatTimeline,
            getLiveAngleDeg = { 20f },
            getLiveAngularVelocityDegPerSec = { 50f },
            hasLiveAngle = { true },
            getVideoPositionMs = { 500 },
            applySpeed = { appliedRate = it },
            nowNanos = { fakeNanos }
        )
        fakeNanos += 75_000_000L
        controller.tick()
        assertEquals(1.0f, appliedRate, 1e-4f)
    }

    @Test
    fun noLiveAngleReadingYetCausesControllerToCoast() {
        // Before the tilt sensor has produced its first reading, there's nothing valid to
        // steer by either -- same fallback as the flat-timeline case.
        val timeline = buildSineTimeline(27.0, 1.87, 30.0, 5.0)
        var fakeNanos = 0L
        var appliedRate = -1f
        val controller = PendulumSpeedController(
            timeline = timeline,
            getLiveAngleDeg = { 20f },
            getLiveAngularVelocityDegPerSec = { 50f },
            hasLiveAngle = { false },
            getVideoPositionMs = { 0 },
            applySpeed = { appliedRate = it },
            nowNanos = { fakeNanos }
        )
        fakeNanos += 75_000_000L
        controller.tick()
        assertEquals(1.0f, appliedRate, 1e-4f)
    }

    /** Simulates the closed loop: each tick, a synthetic live pendulum angle drives the
     * controller, which chooses a playback rate; that rate then advances a simulated video
     * position for the next tick, mirroring what MediaPlayer + a real sensor would do. */
    private fun runSimulation(
        timeline: AngleTimeline,
        liveAmplitudeDeg: Double,
        livePeriodSec: Double,
        ki: Float,
        durationSec: Double = 15.0
    ): DoubleArray {
        var fakeNanos = 0L
        var simTimeSec = 0.0
        var videoPosMs = 0.0
        var lastRate = 1.0f
        val errors = mutableListOf<Double>()

        val controller = PendulumSpeedController(
            timeline = timeline,
            getLiveAngleDeg = {
                (liveAmplitudeDeg * sin(2 * PI * simTimeSec / livePeriodSec)).toFloat()
            },
            getLiveAngularVelocityDegPerSec = {
                (liveAmplitudeDeg * (2 * PI / livePeriodSec) * cos(2 * PI * simTimeSec / livePeriodSec)).toFloat()
            },
            hasLiveAngle = { true },
            getVideoPositionMs = { videoPosMs.toInt() },
            applySpeed = { rate -> lastRate = rate },
            onTick = { info -> info.error?.let { errors.add(it) } },
            nowNanos = { fakeNanos },
            ki = ki
        )

        val tickSec = PendulumTuning.TICK_INTERVAL_MS / 1000.0
        val ticks = (durationSec / tickSec).toInt()
        repeat(ticks) {
            fakeNanos += (tickSec * 1_000_000_000L).toLong()
            simTimeSec += tickSec
            controller.tick()
            videoPosMs = (videoPosMs + lastRate * tickSec * 1000.0)
                .coerceIn(0.0, timeline.durationMs.toDouble())
        }

        return errors.toDoubleArray()
    }

    private fun rms(values: DoubleArray) = sqrt(values.sumOf { it * it } / values.size)

    @Test
    fun integralTermReducesTrackingErrorUnderPeriodMismatch() {
        // The video's own recorded motion has one period; the live pendulum runs at a
        // deliberately different one -- a stand-in for the drift that's guaranteed once a
        // real physical arm replaces any assumed model. python/pendulum_sim_process.md
        // section 9 reports this same comparison in the Python prototype (--period 2.1 vs
        // the footage's true ~1.87s) cut RMS error from ~9.6deg to ~3.4deg by adding Ki=0.3.
        val timeline = buildSineTimeline(amplitudeDeg = 27.0, periodSec = 2.1, fps = 30.0, durationSec = 20.0)

        val kpOnlyErrors = runSimulation(timeline, liveAmplitudeDeg = 27.0, livePeriodSec = 1.87, ki = 0f)
        val withKiErrors = runSimulation(timeline, liveAmplitudeDeg = 27.0, livePeriodSec = 1.87, ki = 0.3f)

        val kpOnlyRms = rms(kpOnlyErrors)
        val withKiRms = rms(withKiErrors)

        assertTrue(
            "expected Ki=0.3 to meaningfully reduce RMS tracking error " +
                "(Kp-only=$kpOnlyRms deg, +Ki=$withKiRms deg)",
            withKiRms < kpOnlyRms * 0.75
        )
    }

    @Test
    fun rateStaysWithinConfiguredBoundsUnderSustainedLargeError() {
        // A basic regression guard on the rate clamp + anti-windup: even under a large,
        // sustained tracking error, the applied rate must never leave [minRate, maxRate].
        val timeline = buildSineTimeline(amplitudeDeg = 27.0, periodSec = 1.87, fps = 30.0, durationSec = 20.0)
        var fakeNanos = 0L
        var lastRate = 1.0f
        var minSeen = Float.MAX_VALUE
        var maxSeen = -Float.MAX_VALUE

        val controller = PendulumSpeedController(
            timeline = timeline,
            getLiveAngleDeg = { 27f },          // pinned at the swing extreme: a persistent, large error
            getLiveAngularVelocityDegPerSec = { 0f },
            hasLiveAngle = { true },
            getVideoPositionMs = { 0 },          // pinned at the opposite extreme of the timeline
            applySpeed = { rate ->
                lastRate = rate
                minSeen = minOf(minSeen, rate)
                maxSeen = maxOf(maxSeen, rate)
            },
            nowNanos = { fakeNanos },
            ki = PendulumTuning.KI
        )

        val tickSec = PendulumTuning.TICK_INTERVAL_MS / 1000.0
        repeat(300) {
            fakeNanos += (tickSec * 1_000_000_000L).toLong()
            controller.tick()
        }

        assertTrue("minSeen=$minSeen below MIN_RATE=${PendulumTuning.MIN_RATE}", minSeen >= PendulumTuning.MIN_RATE)
        assertTrue("maxSeen=$maxSeen above MAX_RATE=${PendulumTuning.MAX_RATE}", maxSeen <= PendulumTuning.MAX_RATE)
    }
}
