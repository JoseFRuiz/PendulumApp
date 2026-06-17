package com.pendulumapp

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import kotlin.math.sqrt

class MotionDetector(
    context: Context,
    private val threshold: Float = DEFAULT_THRESHOLD,
    private val onMotionDetected: () -> Unit
) : SensorEventListener {

    companion object {
        const val DEFAULT_THRESHOLD = 2.0f
        private const val WARMUP_EVENTS = 10
    }

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)

    private var gravityX = 0f
    private var gravityY = 0f
    private var gravityZ = 0f
    private val alpha = 0.8f

    private var warmupCount = 0

    fun startListening() {
        warmupCount = 0
        gravityX = 0f
        gravityY = 0f
        gravityZ = 0f
        accelerometer?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI)
        }
    }

    fun stopListening() {
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ACCELEROMETER) return

        val x = event.values[0]
        val y = event.values[1]
        val z = event.values[2]

        gravityX = alpha * gravityX + (1 - alpha) * x
        gravityY = alpha * gravityY + (1 - alpha) * y
        gravityZ = alpha * gravityZ + (1 - alpha) * z

        warmupCount++
        if (warmupCount < WARMUP_EVENTS) return

        val linearX = x - gravityX
        val linearY = y - gravityY
        val linearZ = z - gravityZ

        val magnitude = sqrt(linearX * linearX + linearY * linearY + linearZ * linearZ)

        if (magnitude > threshold) {
            onMotionDetected()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
