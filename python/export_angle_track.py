"""Export a video's per-frame floor-edge angle timeline as a JSON sidecar file,
for bundling into the Android app alongside the same video (see
pendulum_sim_process.md and the app-port plan for how this is consumed).

Never runs detection itself -- that's floor_edge.py's job (and edit_floor_edge.py/
polish_floor_edge.py's, to build the --reference file this script requires). It only
reshapes that already-detected/corrected/polished track into a small, app-friendly
JSON file.

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

from floor_detection import apply_corrections, load_corrections

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(
    description="Export a video's floor-edge angle timeline as a JSON sidecar for the Android app."
)
parser.add_argument("input_file", nargs="?", default="baile_pendulo_modified.mp4",
                    help="Source video filename in the same folder (default: baile_pendulo_modified.mp4). "
                         "Use the source footage, not a *_pendulum(.mp4|_clean.mp4) render.")
parser.add_argument("--out", default=None,
                    help="Output JSON path (default: <stem>_angles.json next to the input file).")
parser.add_argument("--reference", required=True,
                    help="REQUIRED. This corrections-shaped JSON ({frame_index: [x1,y1,x2,y2]}, one "
                         "entry per frame -- e.g. <stem>_floor_edge_polished.json from "
                         "polish_floor_edge.py, or a hand-edited copy of it, see edit_floor_edge.py "
                         "--corrections) is exported. This script never runs its own detection -- "
                         "that's floor_edge.py's job (and edit_floor_edge.py/polish_floor_edge.py's, "
                         "to build the file you point this at).")
args = parser.parse_args()

input_path  = os.path.join(SCRIPT_DIR, args.input_file)
stem        = os.path.splitext(os.path.basename(args.input_file))[0]
out_path    = args.out or os.path.join(SCRIPT_DIR, f"{stem}_angles.json")

if "_pendulum" in stem:
    print(f"  Warning: '{args.input_file}' looks like a rendered pendulum-preview output, "
          "not source footage. Export from the original video instead.")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps = cap.get(cv2.CAP_PROP_FPS) or 30
cap.release()

reference_path = os.path.join(SCRIPT_DIR, args.reference)
reference = load_corrections(reference_path)
if not reference:
    raise SystemExit(f"--reference {args.reference} not found or empty: {reference_path}")
n = len(reference)
print(f"--reference given: {reference_path} ({n} entries)")
# apply_corrections, reused: a reference file is shaped exactly like a
# corrections file (one line per frame -- see polish_floor_edge.py), so the
# same function that overlays manual corrections fills in both arrays here.
angle_filled, _lines_raw = apply_corrections([None] * n, [None] * n, reference)
detected = [True] * n  # every frame in a reference file counts as ground truth

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
