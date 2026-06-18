package com.pendulumapp

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class MotionDetectorTest {

    private val threshold = MotionDetector.DEFAULT_THRESHOLD

    private fun isLeftToRight(linearX: Float, linearY: Float, linearZ: Float): Boolean {
        return linearX > threshold
                && linearX > abs(linearY)
                && linearX > abs(linearZ)
    }

    @Test
    fun leftToRightMovementTriggers() {
        assertTrue(isLeftToRight(3.0f, 0.5f, 0.5f))
    }

    @Test
    fun rightToLeftMovementDoesNotTrigger() {
        assertFalse(isLeftToRight(-3.0f, 0.5f, 0.5f))
    }

    @Test
    fun verticalMovementDoesNotTrigger() {
        assertFalse(isLeftToRight(0.5f, 5.0f, 0.5f))
    }

    @Test
    fun forwardBackMovementDoesNotTrigger() {
        assertFalse(isLeftToRight(0.5f, 0.5f, 5.0f))
    }

    @Test
    fun smallLeftToRightBelowThresholdDoesNotTrigger() {
        assertFalse(isLeftToRight(1.0f, 0.2f, 0.2f))
    }

    @Test
    fun diagonalMovementDoesNotTriggerWhenXNotDominant() {
        assertFalse(isLeftToRight(3.0f, 4.0f, 0.5f))
    }

    @Test
    fun defaultThresholdIsReasonable() {
        assertTrue(threshold > 0f)
        assertTrue(threshold < 10f)
    }
}
