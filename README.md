# PendulumApp

An Android app that plays a user-selected video whenever it detects a left-to-right swipe of the phone. Right-to-left, vertical, and other movements are ignored.

## Features

- Detects left-to-right phone movement via accelerometer
- Plays and restarts a video from the beginning on each detected swipe
- Video loops continuously until paused or stopped
- No internet connection or special permissions required
- Pick any video from your phone's gallery

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

1. Tap **Select Video** and pick a video from your gallery
2. Tap **Start** to begin motion detection
3. Swipe the phone from **left to right** — the video plays from the beginning
4. Swipe left-to-right again at any time to restart the video
5. Tap **Pause** to temporarily stop detection; tap **Start** again to resume
6. Tap **Stop** to fully stop detection and video playback

---

## Project Structure

```
app/src/main/java/com/pendulumapp/
├── MainActivity.kt       # UI, video picker, state machine
├── MotionDetector.kt     # Accelerometer listener, directional swipe logic
└── AppState.kt           # IDLE / DETECTING / PAUSED enum
```

## Build Commands

```bash
./gradlew assembleDebug           # Build debug APK
./gradlew installDebug            # Build and install on connected device
./gradlew test                    # Run unit tests
./gradlew lint                    # Run lint checks
```

The debug APK is output to `app/build/outputs/apk/debug/app-debug.apk` and can also be sideloaded manually by transferring it to the phone and opening it in a file manager (requires *Install unknown apps* permission).
