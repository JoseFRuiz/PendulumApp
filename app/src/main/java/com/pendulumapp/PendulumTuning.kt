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
     * 2.5 is the best value found so far on the clip actually bundled for the app
     * (python/baile_pendulo.mp4's detected+corrected+polished track), tested together
     * with MIN_RATE/MAX_RATE = 0.70/1.30 below -- the rate bounds genuinely in effect,
     * not Python's wider 0.25-3.0 default. (An earlier, since-superseded round tested
     * under those wider bounds found Ki=0 best; a narrower rate range leaves much less
     * room for the P-term alone to catch up, so it needs more I-term help.) RMS error
     * dropped from 11.8deg at Ki=0 to 5.96deg at Ki=2.5; pushing Ki past ~3.0 starts
     * giving it back (persistent bias grows, then RMS rises again -- classic integral
     * windup onset even with the I_LIMIT anti-windup clamp below). Re-tune on hardware,
     * and re-tune again if MIN_RATE/MAX_RATE/MAX_ACCEL_*_PER_FRAME below ever change --
     * this value is not independent of those.
     */
    const val KI = 2.5f

    /**
     * Derivative gain, dimensionless. Left at 0 (off): python/pendulum_sim_process.md
     * section 9 found it wasn't carrying its weight even with a differenced (noisy) error
     * signal, and here the feedforward term already comes from a live gyroscope reading
     * rather than a differenced angle -- exactly the noise problem Kd would otherwise offset.
     */
    const val KD = 0.0f

    /** Anti-windup clamp on the accumulated integral error, deg*sec. */
    const val I_LIMIT = 15.0

    /** Playback speed multiplier bounds -- matches the range last validated in
     * pendulum_sim.py (--min-rate 0.70 --max-rate 1.30), tighter than Python's own
     * 0.25-3.0 default pending an on-device sweep of audio/decoder quality at more
     * extreme speeds. Keep this in sync with whatever --min-rate/--max-rate the
     * simulation was last run with -- a mismatch here means the app can legally pick
     * rates the simulation never validated. */
    const val MIN_RATE = 0.70f
    const val MAX_RATE = 1.30f

    /** Max change in playback rate per *frame* of the source video (Python units) --
     * multiply by the loaded timeline's fps to get a per-second slew limit at runtime.
     * Matches python/pendulum_sim.py's own --max-accel (slowing down) / --max-accel-up
     * (speeding back up, faster, for quicker recovery after a dip) split, which tested
     * best under MIN_RATE/MAX_RATE = 0.70/1.30 below (RMS 11.8deg, vs 13.4deg for an
     * equal-both-directions 0.08/0.08 under those same bounds -- a different, wider-
     * rate-bounds test once favored the symmetric 0.08/0.08, but that result doesn't
     * hold under the rate bounds actually in effect here; see KI's comment above). */
    const val MAX_ACCEL_DOWN_PER_FRAME = 0.04
    const val MAX_ACCEL_UP_PER_FRAME = 0.08

    /** Local slope (deg per source-frame) below which the signal is treated as flat/no
     * reliable local direction -- multiply by fps for the per-second runtime threshold. */
    const val MIN_SLOPE_DEG_PER_FRAME = 0.05

    /** Minimum change in rate before an actual MediaPlayer.setPlaybackParams() call is
     * made -- avoids audible AudioTrack reconfiguration glitches from frequent near-zero
     * adjustments. The controller's internal rate still updates every tick regardless. */
    const val SPEED_APPLY_EPSILON = 0.005f
}
