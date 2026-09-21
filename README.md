# PendulumApp

An Android app for a physical art installation: a phone mounted on a real swinging
pendulum plays a pre-recorded video, continuously speeding up and slowing down playback
so the video's own recorded floor-tilt cancels the pendulum's live physical tilt — the
recorded floor reads as level to a viewer despite the whole rig visibly swinging. See
`python/pendulum_sim_process.md` for the full design story and `CLAUDE.md` for the
architecture.

## Features

- Continuously tracks the phone's live tilt angle (gravity + gyroscope) and steers video
  playback speed to compensate for it in real time — a feedforward + PID control loop
- Plays a specific, pre-analyzed video bundled with the app (its recorded floor-tilt
  timeline is exported once, offline, via `python/export_angle_track.py`)
- Video loops continuously until paused or stopped
- No internet connection or special permissions required
- A debug-build-only video picker lets you preview an arbitrary video at fixed 1x speed
  (no tracking, since it has no matching timeline) for visual smoke-testing

## Requirements

- Android 8.0 (API 26) or higher
- Android Studio (Hedgehog 2023.1.1 or newer recommended)
- A USB cable to connect your phone for the first install

---

## Build & Install on Galaxy S10

### Step 1 — Enable Developer Options on the phone

1. Open **Settings** on your Galaxy S10
2. Go to **About phone → Software information**
3. Tap **Build number** 7 times in a row
4. You will see the message *"Developer mode has been enabled"*

### Step 2 — Enable USB Debugging

1. Go back to **Settings → Developer options** (now visible at the bottom of Settings)
2. Toggle **USB debugging** to ON
3. Confirm the prompt

### Step 3 — Connect the phone to your PC

1. Plug the Galaxy S10 into your PC via USB cable
2. On the phone, pull down the notification shade and tap the USB notification
3. Select **File Transfer (MTP)** as the connection type
4. A dialog will appear on the phone: *"Allow USB debugging?"* — tap **Allow**
   - Check *"Always allow from this computer"* to avoid seeing this prompt again

### Step 4 — Open the project in Android Studio

1. Launch Android Studio
2. Click **Open** and select the `PendulumApp` folder
3. Wait for Gradle sync to complete (first sync downloads dependencies — may take a few minutes)
4. Your Galaxy S10 should appear in the device dropdown in the toolbar (e.g. *Samsung SM-G973F*)

### Step 5 — Run the app

- Click the green **Run ▶** button in the toolbar, or press `Shift + F10`
- Android Studio will build the APK, install it on the phone, and launch it automatically

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Phone not appearing in Android Studio | Make sure the USB connection mode is File Transfer (MTP), not Charging only |
| "Allow USB debugging?" prompt never appeared | Unplug and replug the USB cable |
| Build fails on first sync | Let the Gradle sync fully complete, then try again |
| Windows doesn't recognize the device | Install **Samsung USB Drivers** via Android Studio → SDK Manager → SDK Tools → Google USB Driver |

---

## How to Use

1. Tap **Start** — the bundled video plays immediately and the app begins tracking the
   phone's live tilt to steer playback speed
2. Mount the phone on the pendulum arm and let it swing — the recorded floor should read
   as level despite the physical swinging (see `python/pendulum_sim_process.md`)
3. Tap **Pause** to temporarily stop tracking and playback; tap **Start** again to resume
4. Tap **Stop** to fully stop and reset back to the beginning
5. (Debug builds only) **Select Video** picks an arbitrary video to preview at a fixed
   1x speed, with no pendulum tracking — for visual smoke-testing only

---

## Project Structure

```
app/src/main/java/com/pendulumapp/
├── MainActivity.kt              # UI, playback, state machine, control-loop wiring
├── PendulumTiltSensor.kt        # Live tilt angle + angular velocity (gravity + gyroscope)
├── PendulumSpeedController.kt   # Feedforward + PID control loop -> playback speed
├── AngleTimeline.kt             # Loads/interpolates a video's exported angle track
├── PendulumTuning.kt            # Kp/Ki/Kd and other tunable constants
└── AppState.kt                  # IDLE / DETECTING / PAUSED enum

app/src/main/assets/
├── dancer.mp4                   # The installation's video (source footage)
└── dancer_angles.json           # Its recorded floor-tilt timeline, from export_angle_track.py

python/
├── pendulum_sim.py              # PC-side prototype/reference for the control law
├── pendulum_sim_process.md      # Design write-up -- read this first
└── export_angle_track.py        # Generates the JSON sidecar bundled above
```

## Build Commands

```bash
./gradlew assembleDebug           # Build debug APK
./gradlew installDebug            # Build and install on connected device
./gradlew test                    # Run unit tests
./gradlew lint                    # Run lint checks
```

The debug APK is output to `app/build/outputs/apk/debug/app-debug.apk` and can also be sideloaded manually by transferring it to the phone and opening it in a file manager (requires *Install unknown apps* permission).
