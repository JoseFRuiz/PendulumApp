# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
./gradlew assembleDebug                        # Debug build
./gradlew assembleRelease                      # Release build
./gradlew test                                 # Run all unit tests
./gradlew test --tests MotionDetectorTest      # Run a single test class
./gradlew lint                                 # Android lint
./gradlew installDebug                         # Build + install on connected device
```

## Architecture

Single-activity Android app (Kotlin) that plays a user-selected video when phone movement is detected via the accelerometer. Three source files in `app/src/main/java/com/pendulumapp/`:

- **MainActivity.kt** — Orchestrates video picker (`ActivityResultContracts.OpenDocument`), `MediaPlayer` + `TextureView` playback, `MotionDetector` lifecycle, and a state machine driving button enable/disable. Uses ViewBinding. Implements `TextureView.SurfaceTextureListener` to manage the `Surface` lifecycle. Sensor listener unregisters in `onPause()` and re-registers in `onResume()` when in DETECTING state. After stop, `setupMediaPlayer()` is called again to reset the player. A 1-second `Handler` delay after pressing Start prevents the tap vibration from triggering detection immediately.

- **MotionDetector.kt** — `SensorEventListener` on `TYPE_LINEAR_ACCELERATION` (OS sensor-fusion virtual sensor that removes gravity via accelerometer + gyroscope, so pure rotation does not trigger it). Detects left-to-right swipes: positive X above threshold (2.0 m/s²) with X dominant over Y and Z. 800ms cooldown prevents double-firing per swing. 10-event warmup after registration. Callback fires on the sensor thread — caller must post to main thread.

- **AppState.kt** — `DetectionState` enum (`IDLE`, `DETECTING`, `PAUSED`) controls UI state and sensor registration.

## Build Configuration

- AGP 8.13.2, Kotlin 1.9.21, Gradle 8.13 (Kotlin DSL)
- minSdk 26, targetSdk/compileSdk 34, Java 17
- No runtime permissions — `OpenDocument` contract grants persistent URI access
- Portrait orientation locked in manifest
