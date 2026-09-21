package com.pendulumapp

/**
 * Tunable constants for [PendulumSpeedController]. Ported from python/pendulum_sim.py's
 * --kp/--ki/--kd/--min-rate/--max-rate/--max-accel/--i-limit flags -- see
 * python/pendulum_sim_process.md section 9 for why the control law is shaped this way.
 *
 * Kp, Ki, I_LIMIT are already expressed in per-second units in the Python source, so they
 * port directly. MAX_ACCEL and MIN_SLOPE_DEG were expressed per-*frame* in Python (an
 * offline, frame-indexed loop); here they're re-derived per-*second* at runtime from the
 * loaded video's actual fps (see PendulumSpeedController), since this control loop runs on
 * a real-time timer, not a frame loop.
 */
object PendulumTuning {
    /** Control-loop tick interval, milliseconds. */
    const val TICK_INTERVAL_MS = 75L

    /** Proportional gain, 1/sec: deg/sec of correction per degree of position error. */
    const val KP = 1.667f

    /**
     * Integral gain, 1/sec^2: deg/sec of correction per (deg*sec) of accumulated error.
     * Python's own shipped default is 0.0 (off), but this repo's comparison testing found
     * 0.3 cut RMS tracking error roughly in half to two-thirds versus Kp alone -- start from
     * that tested value, not the off-by-default Python CLI default, and re-tune on hardware.
     */
    const val KI = 0.3f

    /**
     * Derivative gain, dimensionless. Left at 0 (off): python/pendulum_sim_process.md
     * section 9 found it wasn't carrying its weight even with a differenced (noisy) error
     * signal, and here the feedforward term already comes from a live gyroscope reading
     * rather than a differenced angle -- exactly the noise problem Kd would otherwise offset.
     */
    const val KD = 0.0f

    /** Anti-windup clamp on the accumulated integral error, deg*sec. */
    const val I_LIMIT = 15.0

    /** Playback speed multiplier bounds. Tightened from Python's 0.25-3.0 pending an
     * on-device sweep of audio/decoder quality at extreme speeds -- see the plan's notes
     * on MediaPlayer.PlaybackParams behavior. */
    const val MIN_RATE = 0.5f
    const val MAX_RATE = 2.0f

    /** Max change in playback rate per *frame* of the source video (Python units) --
     * multiply by the loaded timeline's fps to get a per-second slew limit at runtime. */
    const val MAX_ACCEL_PER_FRAME = 0.04

    /** Local slope (deg per source-frame) below which the signal is treated as flat/no
     * reliable local direction -- multiply by fps for the per-second runtime threshold. */
    const val MIN_SLOPE_DEG_PER_FRAME = 0.05

    /** Minimum change in rate before an actual MediaPlayer.setPlaybackParams() call is
     * made -- avoids audible AudioTrack reconfiguration glitches from frequent near-zero
     * adjustments. The controller's internal rate still updates every tick regardless. */
    const val SPEED_APPLY_EPSILON = 0.005f
}
