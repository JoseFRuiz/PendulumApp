package com.pendulumapp

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AngleTimelineTest {

    private fun timeline() = AngleTimeline.fromArrays(
        tMs = intArrayOf(0, 100, 200, 300),
        angleDeg = floatArrayOf(0f, 10f, 10f, -20f),
        fps = 10.0,
        durationMs = 300
    )

    @Test
    fun lookupAtExactSamplePointReturnsThatValue() {
        val t = timeline()
        assertEquals(10.0, t.lookup(100)!!.realHere, 1e-9)
    }

    @Test
    fun lookupBetweenSamplesInterpolatesLinearly() {
        val t = timeline()
        // Halfway between t=0 (angle 0) and t=100 (angle 10)
        assertEquals(5.0, t.lookup(50)!!.realHere, 1e-9)
    }

    @Test
    fun lookupClampsBeforeStartAndAfterEnd() {
        val t = timeline()
        assertEquals(0.0, t.lookup(-500)!!.realHere, 1e-9)
        assertEquals(-20.0, t.lookup(9999)!!.realHere, 1e-9)
    }

    @Test
    fun localSlopeIsZeroOnAFlatSpan() {
        val t = timeline()
        // Between t=100 and t=200 the angle is flat (10 -> 10)
        assertEquals(0.0, t.lookup(150)!!.localSlopePerSec, 1e-9)
    }

    @Test
    fun localSlopeIsExpressedPerSecondOfVideoTime() {
        val t = timeline()
        // Between t=200 (angle 10) and t=300 (angle -20): -30 deg over 100ms = -300 deg/sec
        assertEquals(-300.0, t.lookup(250)!!.localSlopePerSec, 1e-6)
    }

    @Test
    fun tooFewSamplesReturnsNull() {
        val t = AngleTimeline.fromArrays(intArrayOf(0), floatArrayOf(0f), 10.0, 0)
        assertNull(t.lookup(0))
    }
}
