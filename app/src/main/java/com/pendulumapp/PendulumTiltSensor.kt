package com.pendulumapp

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import kotlin.math.atan2

/**
 * Continuous live tilt-angle sensor for the phone mounted on the physical pendulum.
 * Replaces MotionDetector's discrete swing-detection: instead of a one-shot "a swing just
 * happened" callback, this exposes the pendulum's current angle and angular velocity as
 * plain fields, polled by [PendulumSpeedController]'s own timer -- see
 * python/pendulum_sim_process.md section 7 for why continuous tracking supersedes discrete
 * triggering.
 *
 * Angle comes from TYPE_GRAVITY: projecting the gravity vector onto the swing plane gives
 * "angle from vertical" directly via one atan2 call -- drift-free, since it's referenced to
 * gravity rather than integrated, unlike a gyroscope-only estimate. This is the most direct
 * on-device analog of "a pendulum's angle from vertical."
 *
 * Angular velocity comes from TYPE_GYROSCOPE directly, rather than numerically differencing
 * the angle signal -- a cleaner feedforward source that avoids amplifying sensor noise (the
 * same noise-sensitivity problem python/pendulum_sim_process.md section 9 flags for a
 * differenced-signal derivative term).
 *
 * AXIS CALIBRATION -- confirmed from an on-device log (see python/plot_debug_log.py's raw
 * gravity-axis summary), not guessed:
 *   gravityX: mean +9.38, spread 1.64  -> near +-9.8 at rest: this is the DOWN axis
 *   gravityY: mean -0.14, spread 8.73  -> by far the largest swing: this is the SWING axis
 *   gravityZ: mean -0.16, spread 0.54  -> flat/noise: irrelevant
 * i.e. the phone is mounted with its screen roughly *vertical* (gravity sits on device X at
 * rest), not flat as this class originally assumed (it shipped assuming device Z was "down",
 * which matches a flat-on-a-table mounting, not an upright swinging one). [downAxisIndex]/
 * [swingAxisIndex] encode that finding as data rather than an enum choice, and
 * [rotationAxisIndex] is derived from them: the gyroscope component that measures rotation
 * *about* the axis perpendicular to the down/swing plane is whichever of {0,1,2} isn't one of
 * those two -- previously this read gyroX unconditionally, which was wrong for the same
 * reason the down axis was wrong.
 *
 * [invertSign] RE-VERIFIED after the axis fix above, and flipped: changing which raw axis
 * angleDeg is computed from (down axis Z -> X) changes the effective handedness of the
 * measured angle, so the correct sign changed too, as expected. Confirmed from a real log
 * (see python/plot_debug_log.py / the correlation check it's based on): with invertSign=true,
 * target and realHere were WEAKLY ANTI-correlated (~-0.3) -- the controller was pushing the
 * wrong direction on average, not just failing to converge. With invertSign=false, that
 * relationship flips to weakly positive, the right sign (further tuning may still be needed
 * for strength of tracking, but the *direction* is now correct). If the mounting changes
 * again, re-check this the same way: pull a log, correlate `targetDeg` against `realHereDeg`
 * -- it should come out positive, not negative. python/pendulum_sim_process.md section 6
 * describes what "doubling instead of compensating" (i.e. the sign backwards) looks like.
 */
class PendulumTiltSensor(
    context: Context,
    private val downAxisIndex: Int = 0,   // gravityX: confirmed "down" at rest, see class doc
    private val swingAxisIndex: Int = 1,  // gravityY: confirmed swing axis, see class doc
    private val invertSign: Boolean = false
) : SensorEventListener {

    // The remaining axis (0+1+2=3, so whichever index isn't downAxisIndex or swingAxisIndex)
    // is the one the gyroscope should read: rotation about the axis perpendicular to the
    // down/swing plane is exactly what changes the down/swing-plane angle over time.
    private val rotationAxisIndex: Int = 3 - downAxisIndex - swingAxisIndex

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val gravitySensor = sensorManager.getDefaultSensor(Sensor.TYPE_GRAVITY)
    private val gyroSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    /** Live tilt angle from vertical, degrees. Sign convention: see class doc's AXIS CALIBRATION. */
    @Volatile
    var angleDeg: Float = 0f
        private set

    /** Live angular velocity, degrees/sec, same sign convention as [angleDeg]. */
    @Volatile
    var angularVelocityDegPerSec: Float = 0f
        private set

    /** True once at least one gravity reading has arrived, i.e. [angleDeg] is meaningful. */
    @Volatile
    var hasAngleReading: Boolean = false
        private set

    // Raw per-axis sensor values (device coordinates, m/s^2 and rad/s respectively),
    // captured unconditionally regardless of downAxisIndex/swingAxisIndex/invertSign -- this
    // is the actual data python/plot_debug_log.py's raw-gravity-axis summary was built from,
    // and is what to re-check first if the mounting ever changes again. See PendulumDebugLogger,
    // which logs these to the CSV.
    @Volatile var gravityX: Float = 0f; private set
    @Volatile var gravityY: Float = 0f; private set
    @Volatile var gravityZ: Float = 0f; private set
    @Volatile var gyroX: Float = 0f; private set
    @Volatile var gyroY: Float = 0f; private set
    @Volatile var gyroZ: Float = 0f; private set

    fun start() {
        gravitySensor?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
        gyroSensor?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
    }

    fun stop() {
        sensorManager.unregisterListener(this)
        hasAngleReading = false
    }

    override fun onSensorChanged(event: SensorEvent) {
        val sign = if (invertSign) -1.0 else 1.0
        when (event.sensor.type) {
            Sensor.TYPE_GRAVITY -> {
                gravityX = event.values[0]
                gravityY = event.values[1]
                gravityZ = event.values[2]

                val swingComponent = event.values[swingAxisIndex]
                val downComponent = event.values[downAxisIndex]
                val raw = Math.toDegrees(atan2(swingComponent.toDouble(), downComponent.toDouble()))
                angleDeg = (sign * raw).toFloat()
                hasAngleReading = true
            }
            Sensor.TYPE_GYROSCOPE -> {
                gyroX = event.values[0]
                gyroY = event.values[1]
                gyroZ = event.values[2]

                val omegaRad = event.values[rotationAxisIndex]
                angularVelocityDegPerSec = (sign * Math.toDegrees(omegaRad.toDouble())).toFloat()
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
