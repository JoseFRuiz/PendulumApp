"""Export a video's per-frame floor-edge angle timeline as a JSON sidecar file,
for bundling into the Android app alongside the same video (see
pendulum_sim_process.md and the app-port plan for how this is consumed).

Reuses floor_detection.detect_sequence/fill_gaps unchanged -- this script does not
reimplement detection, it only reshapes the same offline-analysis output pendulum_sim.py
already relies on into a small, app-friendly JSON file.

IMPORTANT -- run this against the *source* footage (e.g. baile_pendulo_modified.mp4),
never against a *_pendulum.mp4 / *_pendulum_clean.mp4 output. Those are the PC-side
preview of the whole installation effect (composited canvas, arm, pivot); the phone
plays the raw source footage and does the compositing live, via its own screen
rotation and playback speed.

Sign convention -- the exported angleDeg array is angle_filled as-is (the same sign
pendulum_sim.py uses for `real_here` in its control law), NOT the negated value
pendulum_sim.py only uses for its diagnostic plot (floor_angle_history). Whatever
consumes this JSON must apply the negation itself, at the same point pendulum_sim.py
does (target_deg = -live_angle), or it will reproduce the sign bug documented in
pendulum_sim_process.md section 6 (arm and floor doubling the tilt instead of
cancelling it).
"""

import argparse
import json
import os

import cv2

from floor_detection import detect_sequence, fill_gaps

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(
    description="Export a video's floor-edge angle timeline as a JSON sidecar for the Android app."
)
parser.add_argument("input_file", nargs="?", default="baile_pendulo_modified.mp4",
                    help="Source video filename in the same folder (default: baile_pendulo_modified.mp4). "
                         "Use the source footage, not a *_pendulum(.mp4|_clean.mp4) render.")
parser.add_argument("--out", default=None,
                    help="Output JSON path (default: <stem>_angles.json next to the input file).")
args = parser.parse_args()

input_path = os.path.join(SCRIPT_DIR, args.input_file)
stem       = os.path.splitext(os.path.basename(args.input_file))[0]
out_path   = args.out or os.path.join(SCRIPT_DIR, f"{stem}_angles.json")

if "_pendulum" in stem:
    print(f"  Warning: '{args.input_file}' looks like a rendered pendulum-preview output, "
          "not source footage. Export from the original video instead.")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

print(f"Analyzing floor edge angle in {args.input_file} ({total_frames} frames @ {fps:.2f} fps)...")
detections = detect_sequence(cap, progress_label="detect")
cap.release()

raw_angles   = [a for a, _ in detections]
angle_filled = fill_gaps(raw_angles)
detected     = [a is not None for a in raw_angles]

n = len(angle_filled)
coverage_pct = 100.0 * sum(detected) / n if n > 0 else 0.0
print(f"  {sum(detected)}/{n} frames detected directly ({coverage_pct:.1f}%); "
      f"the rest filled by carrying the nearest valid detection forward/backward.")

use_fallback = all(a is None for a in raw_angles)
if use_fallback:
    print("  Warning: no floor edge detected anywhere in this video; the exported "
          "angleDeg values are meaningless (all held at 0). Do not bundle this timeline.")

t_ms = [round(i * 1000 / fps) for i in range(n)]
angle_deg = [round(float(a), 3) if a is not None else 0.0 for a in angle_filled]

payload = {
    "schemaVersion": 1,
    "sourceVideo": args.input_file,
    "fps": fps,
    "frameCount": n,
    "durationMs": t_ms[-1] if t_ms else 0,
    "tMs": t_ms,
    "angleDeg": angle_deg,
    "detected": detected,
}

with open(out_path, "w") as f:
    json.dump(payload, f)

print(f"\nDone. Saved to:\n  {out_path}")
