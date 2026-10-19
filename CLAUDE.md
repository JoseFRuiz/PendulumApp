# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
./gradlew assembleDebug                                    # Debug build
./gradlew assembleRelease                                  # Release build
./gradlew test                                              # Run all unit tests
./gradlew test --tests PendulumSpeedControllerTest          # Run a single test class
./gradlew lint                                              # Android lint
./gradlew installDebug                                      # Build + install on connected device
```

## Architecture

Single-activity Android app (Kotlin): a phone/screen mounted on a real swinging pendulum
plays a pre-recorded video, continuously adjusting *playback speed* (never the pendulum's
physical motion, which software can't touch) so the video's own recorded floor-tilt cancels
the pendulum's live physical tilt — see `python/pendulum_sim_process.md` for the full design
rationale and `python/pendulum_sim.py` for the PC-side prototype this app ports. Source files
in `app/src/main/java/com/pendulumapp/`:

- **MainActivity.kt** — Orchestrates `MediaPlayer` + `TextureView` playback, the
  `PendulumTiltSensor`/`PendulumSpeedController` lifecycle, and a state machine driving button
  enable/disable. Uses ViewBinding. Implements `TextureView.SurfaceTextureListener` to manage
  the `Surface` lifecycle. Pressing Start plays the bundled video immediately and starts a
  ~75ms self-rescheduling `Handler` loop that ticks `PendulumSpeedController` and applies its
  chosen rate via `MediaPlayer.PlaybackParams`. A debug-only SAF video picker
  (`ActivityResultContracts.OpenDocument`, gated behind `BuildConfig.DEBUG`) plays an arbitrary
  picked video at a fixed 1x with no tracking, for visual smoke-testing only.

- **PendulumTiltSensor.kt** — Continuous live tilt-angle sensor (replaces the old discrete
  swing-detector). Reads `TYPE_GRAVITY` (angle from vertical via one `atan2`, drift-free) and
  `TYPE_GYROSCOPE` (angular velocity directly, a cleaner feedforward source than differencing
  a noisy angle signal). Poll-based (`angleDeg`/`angularVelocityDegPerSec` fields), not
  callback-based — the control loop's own timer decides when to read them. `downAxisIndex`/
  `swingAxisIndex` (which raw gravity axis is "down" vs. the swing plane) are now calibrated
  from an actual on-device log, not guessed — see the class doc comment for the numbers and
  `PendulumDebugLogger`/`python/plot_debug_log.py` for how they were obtained. `invertSign`
  still needs re-verification any time the mounting changes, since it's tuned against that
  axis geometry.

- **PendulumSpeedController.kt** — The ported feedforward + PID control law (see
  `python/pendulum_sim_process.md` sections 4/9): continuously computes a playback-speed
  multiplier from the live pendulum angle/rate and the video's own recorded-angle timeline at
  its current playback position. Dependencies are plain lambdas (not concrete Android types),
  so the control math is unit-testable with fakes — see `PendulumSpeedControllerTest`.

- **AngleTimeline.kt** — Loads a video's per-frame recorded floor-edge angle from a JSON
  sidecar exported offline by `python/export_angle_track.py` (bundled as an Android asset
  alongside the video, e.g. `dancer.mp4` + `dancer_angles.json`). Provides an interpolated
  lookup by playback position in milliseconds.

- **PendulumTuning.kt** — Tunable constants (`Kp`/`Ki`/`Kd`, rate limits, tick interval) in one
  place, with notes on how each maps to (or was re-derived from) `pendulum_sim.py`'s CLI flags.

- **AppState.kt** — `DetectionState` enum (`IDLE`, `DETECTING`, `PAUSED`) controls UI state and
  sensor/control-loop registration; unchanged in shape from before, just what happens inside
  `DETECTING` changed (continuous tracking instead of arm-and-wait-for-a-swing).

## Build Configuration

- AGP 8.13.2, Kotlin 1.9.21, Gradle 8.13 (Kotlin DSL)
- minSdk 26, targetSdk/compileSdk 34, Java 17
- `buildFeatures.buildConfig = true` — needed for `BuildConfig.DEBUG` gating (dev picker, debug readout)
- No runtime permissions — `OpenDocument` contract grants persistent URI access; motion sensors need none either
- Portrait orientation locked in manifest

## Bundled video asset

`app/src/main/assets/dancer.mp4` + `dancer_angles.json` are the installation's actual content.
Producing `dancer_angles.json` is a pipeline of four scripts, each reusing the previous one's
output (see `python/edit_floor_edge.py`'s docstring for the authoritative step-by-step):

1. `python floor_edge.py <source_video>.mp4` — runs the Hough-transform detection
   (`floor_detection.py`'s `FloorEdgeDetector`) and renders a preview video + angle plot. It's
   the one script still allowed to run detection standalone (no `--reference` needed); useful to
   eyeball whether the auto-detection is any good before touching anything else.
2. `python edit_floor_edge.py <source_video>.mp4` — interactive frame-by-frame reviewer/editor
   for frames the detector got wrong (wrong line, or none at all): auto-jumps to frames flagged
   as suspect (no detection, or a sudden angle jump), lets you click-drag a replacement line
   (auto-extended across the full frame width, same as the detector's own output — see
   `floor_detection.fit_full_width_line`), and saves overrides to
   `<stem>_floor_edge_corrections.json`.
3. `python polish_floor_edge.py <source_video>.mp4` — smooths the detected+corrected track into
   a locally-sinusoidal, fixed-pivot reference (manually corrected frames are passed through as
   trusted anchors, so the fit bends toward them rather than averaging them away) and writes
   `<stem>_floor_edge_polished.json`, in the same `{frame_index: [x1,y1,x2,y2]}` shape as the
   corrections file (loadable the same way, and itself re-editable via `edit_floor_edge.py
   <video>.mp4 --corrections <stem>_floor_edge_polished.json`).
4. `python export_angle_track.py <source_video>.mp4 --reference <stem>_floor_edge_polished.json`
   — the one that actually matters for the installation; see `python/export_angle_track.py`'s
   docstring. Must run against source footage, never a `*_pendulum.mp4`/`*_pendulum_clean.mp4`
   render. `--reference` is required — this script (like `pendulum_sim.py`) never runs detection
   itself, only `floor_edge.py`/`edit_floor_edge.py`/`polish_floor_edge.py` do.

To swap the installation's video, redo this whole pipeline against the new source footage and
replace both files in `assets/` together — they must correspond to the same footage, or the
control loop steers against the wrong timeline.
