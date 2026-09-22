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
 * BRING-UP, NOT RESOLVABLE ON PAPER:
 *  - [axis] picks which device axis lies in the swing plane; this depends on how the phone
 *    is physically mounted on the arm and can only be determined by testing on the real
 *    hardware -- swing the phone by hand, log angleDeg, and confirm it changes sensibly.
 *  - [invertSign] was confirmed needed on hardware: on-device testing found the raw sensor
 *    sign made the video's rotation *double* the pendulum's live tilt instead of cancelling
 *    it (target = -angleDeg in PendulumSpeedController was fighting the wrong direction) --
 *    the exact class of bug python/pendulum_sim_process.md section 6 documents on the
 *    Python side. If the physical mounting orientation changes, re-verify this by hand
 *    (swing the phone, log angleDeg) rather than assuming the same sign still applies.
 */
class PendulumTiltSensor(
    context: Context,
    private val axis: Axis = Axis.Y,
    private val invertSign: Boolean = true
) : SensorEventListener {

    enum class Axis { X, Y }

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val gravitySensor = sensorManager.getDefaultSensor(Sensor.TYPE_GRAVITY)
    private val gyroSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    /** Live tilt angle from vertical, degrees. Sign convention: see class doc, bring-up. */
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
                val swingComponent = if (axis == Axis.Y) event.values[1] else event.values[0]
                val downComponent = event.values[2]
                val raw = Math.toDegrees(atan2(swingComponent.toDouble(), downComponent.toDouble()))
                angleDeg = (sign * raw).toFloat()
                hasAngleReading = true
            }
            Sensor.TYPE_GYROSCOPE -> {
                val omegaRad = if (axis == Axis.Y) event.values[0] else event.values[1]
                angularVelocityDegPerSec = (sign * Math.toDegrees(omegaRad.toDouble())).toFloat()
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
