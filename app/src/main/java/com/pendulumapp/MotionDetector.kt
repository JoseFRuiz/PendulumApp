package com.pendulumapp

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import kotlin.math.abs

class MotionDetector(
    context: Context,
    private val threshold: Float = DEFAULT_THRESHOLD,
    private val onMotionDetected: () -> Unit
) : SensorEventListener {

    companion object {
        const val DEFAULT_THRESHOLD = 2.0f
        private const val WARMUP_EVENTS = 10
        private const val COOLDOWN_MS = 400L
    }

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val linearAccelSensor = sensorManager.getDefaultSensor(Sensor.TYPE_LINEAR_ACCELERATION)

    private var warmupCount = 0
    private var lastTriggerTime = 0L
    // True while the swing Y magnitude is above the threshold (approaching or at the extreme)
    private var inExtreme = false

    fun startListening() {
        warmupCount = 0
        lastTriggerTime = 0L
        inExtreme = false
        linearAccelSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI)
        }
    }

    fun stopListening() {
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_LINEAR_ACCELERATION) return

        warmupCount++
        if (warmupCount < WARMUP_EVENTS) return

        val linearX = event.values[0]
        val linearY = event.values[1]
        val linearZ = event.values[2]

        // Negative Y = top-to-bottom motion → detects one specific extreme of the pendulum.
        // If the wrong extreme triggers, change -linearY to +linearY on the next line.
        val swingY = -linearY
        val isYDominant = swingY > abs(linearX) && swingY > abs(linearZ)

        // Rising edge: entering the extreme zone
        if (isYDominant && swingY > threshold) {
            inExtreme = true
        }

        // Falling edge: the extreme has just been passed and the phone is returning to center.
        // Fire here — once per extreme, at a consistent point in the arc.
        if (inExtreme && swingY < threshold * 0.5f) {
            inExtreme = false
            val now = System.currentTimeMillis()
            if (now - lastTriggerTime > COOLDOWN_MS) {
                lastTriggerTime = now
                onMotionDetected()
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
