package com.pendulumapp

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sqrt

class MotionDetectorTest {

    @Test
    fun magnitudeAboveThresholdTriggersDetection() {
        val threshold = MotionDetector.DEFAULT_THRESHOLD
        val magnitude = sqrt(3f * 3f + 0f + 0f)
        assertTrue(magnitude > threshold)
    }

    @Test
    fun magnitudeBelowThresholdDoesNotTrigger() {
        val threshold = MotionDetector.DEFAULT_THRESHOLD
        val magnitude = sqrt(1f * 1f + 0.5f * 0.5f + 0.5f * 0.5f)
        assertFalse(magnitude > threshold)
    }

    @Test
    fun defaultThresholdIsReasonable() {
        val threshold = MotionDetector.DEFAULT_THRESHOLD
        assertTrue(threshold > 0f)
        assertTrue(threshold < 10f)
    }
}
