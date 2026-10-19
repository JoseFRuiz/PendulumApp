# Run: python polish_floor_edge.py baile_pendulo.mp4

"""Generate a polished (smoothed, locally-sinusoidal, fixed-pivot) version of a
video's detected floor-edge angle track and save it as <stem>_floor_edge_polished.json
-- deliberately the same shape as <stem>_floor_edge_corrections.json from
edit_floor_edge.py ({frame_index: [x1, y1, x2, y2]}, loadable with the same
load_corrections/apply_corrections), just with every frame populated instead of
only the manually-fixed ones. One line per frame is enough: its angle (recoverable
via line_angle_deg) IS the smoothed value, and its position already pivots about
the fixed centerY described below -- there's no separate unpivoted angle to also
carry around.

Reuses the same cached detection (<stem>_floor_edge_detection_cache.json, shared
with edit_floor_edge.py) and manual corrections (<stem>_floor_edge_corrections.json,
from edit_floor_edge.py) as every other script in this pipeline -- this script does
not redetect or reinterpret anything, it only smooths what's already been detected
and corrected, via floor_detection.polish_sinusoidal. Manually corrected frames are
passed through as `trusted`, so the fit is pulled toward them and never treats them
as outliers to reject, instead of averaging them in as just more (possibly noisy)
samples alongside the auto-detected ones.

Pass --reference to re-polish from an existing corrections-shaped track instead of
raw detection -- e.g. to repeat the smoothing pass over the very file you've just
hand-edited (see edit_floor_edge.py --corrections), rather than starting over from
scratch and losing those edits:
  python edit_floor_edge.py baile_pendulo.mp4 --corrections baile_pendulo_floor_edge_polished.json
  python polish_floor_edge.py baile_pendulo.mp4 --reference baile_pendulo_floor_edge_polished.json
This skips detection/the cache entirely and uses --reference as the starting track
(its per-frame lines become the fit's input, not its output). <stem>_floor_edge_
corrections.json is still applied and trusted on top as usual -- --reference only
replaces the raw-detection baseline, not the separate manual-corrections step.

Also computes a single fixed centerY: the per-frame detected/corrected lines are
already full-width, so each one's value at the frame's horizontal center is just
(y1+y2)/2; centerY is the average of that across every frame with a line. The real
floor edge shouldn't translate up and down frame to frame -- only its apparent
angle should change -- so the saved line pivots about this one fixed point (see
floor_detection.line_from_angle) rather than each frame's own (noisier) fitted
position.

The output is a single source of truth read by:
  python floor_edge.py <video> --reference <out>          # see it drawn in the video/plot
  python pendulum_sim.py <video> --reference <out>         # preview it driving the controller
  python export_angle_track.py <video> --reference <out>   # bundle it into the Android app

Re-run this whenever the detection, corrections, or --period change -- the
consumers above check it has exactly one entry per frame and refuse a stale or
mismatched file rather than silently using outdated polish data.

Usage:
  python polish_floor_edge.py baile_pendulo.mp4
  python polish_floor_edge.py baile_pendulo.mp4 --period 1.87
"""

import argparse
import os

import cv2
import numpy as np

from floor_detection import (apply_corrections, detect_sequence, fill_gaps, line_from_angle,
                              load_corrections, load_detection_cache, polish_sinusoidal,
                              save_corrections, save_detection_cache)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("input_file", nargs="?", default="baile_pendulo.mp4",
                    help="Input video filename in the same folder (default: baile_pendulo.mp4)")
parser.add_argument("--period", type=float, default=None,
                    help="Expected oscillation period in seconds (default: estimated from the "
                         "detected track itself via FFT, same method floor_edge.py uses).")
parser.add_argument("--redetect", action="store_true",
                    help="Force a fresh detection pass instead of reusing a cached one. Ignored "
                         "with --reference, which skips detection/the cache entirely.")
parser.add_argument("--reference", default=None,
                    help="Re-polish from this corrections-shaped JSON ({frame_index: "
                         "[x1,y1,x2,y2]}, one entry per frame -- e.g. a previous "
                         "<stem>_floor_edge_polished.json you've hand-edited) instead of raw "
                         "detection. Skips detection/the cache entirely; <stem>_floor_edge_"
                         "corrections.json is still applied and trusted on top as usual.")
args = parser.parse_args()

input_path = os.path.join(SCRIPT_DIR, args.input_file)
stem       = os.path.splitext(os.path.basename(args.input_file))[0]
cache_path = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_detection_cache.json")
corr_path  = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_corrections.json")
out_path   = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_polished.json")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
vw           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

if args.reference:
    # A reference file already has one line per frame -- running detection just to
    # immediately throw its result away would be pure waste, so it's skipped
    # entirely rather than run and then overridden (same reasoning as --reference
    # in floor_edge.py/pendulum_sim.py/export_angle_track.py).
    cap.release()
    reference_path = os.path.join(SCRIPT_DIR, args.reference)
    reference = load_corrections(reference_path)
    if not reference:
        raise SystemExit(f"--reference {args.reference} not found or empty: {reference_path}")
    print(f"--reference given: {reference_path} ({len(reference)} entries) -- "
          f"skipping raw detection entirely")
    # apply_corrections, reused: a reference file is shaped exactly like a
    # corrections file (one line per frame), so the same function that overlays
    # manual corrections elsewhere fills in both arrays here.
    raw_angles, lines_raw = apply_corrections([None] * len(reference), [None] * len(reference),
                                               reference)
else:
    cached = None if args.redetect else load_detection_cache(cache_path, args.input_file, total_frames)
    if cached is not None:
        raw_angles, lines_raw = cached
        print(f"Using cached detection from {cache_path} ({len(raw_angles)} frames).")
    else:
        print(f"Detecting floor edge angle in {args.input_file} ({total_frames} frames @ {fps:.2f} fps)...")
        detections = detect_sequence(cap, progress_label="detect")
        raw_angles = [a for a, _ in detections]
        lines_raw  = [l for _, l in detections]
        save_detection_cache(cache_path, args.input_file, total_frames, raw_angles, lines_raw)
    cap.release()

corrections = load_corrections(corr_path)
if corrections:
    print(f"  Applying {len(corrections)} manual correction(s) from {corr_path}")
    raw_angles, lines_raw = apply_corrections(raw_angles, lines_raw, corrections)
else:
    print(f"  No manual corrections found at {corr_path}")

angle_filled = np.array(fill_gaps(raw_angles), dtype=float)

period = args.period
if period is None:
    fft_mag = np.abs(np.fft.rfft(angle_filled - angle_filled.mean()))
    freqs   = np.fft.rfftfreq(len(angle_filled), d=1.0 / fps)
    peak_f  = freqs[np.argmax(fft_mag[1:]) + 1]  # [1:] skips DC
    period  = 1.0 / peak_f if peak_f > 0 else 2.0
    print(f"  Estimated period {period:.2f}s from the track itself (FFT)")

trusted = np.zeros(len(angle_filled), dtype=bool)
for idx in corrections:
    if 0 <= idx < len(trusted):
        trusted[idx] = True
if corrections:
    print(f"  {trusted.sum()} frame(s) marked trusted (manually corrected) -- the fit is "
          f"pulled toward these and never rejects them as outliers")

print("Fitting local sinusoids...")
polished = polish_sinusoidal(angle_filled, fps, period, trusted=trusted)

center_ys = [(l[1] + l[3]) / 2.0 for l in lines_raw if l is not None]
center_y  = float(np.mean(center_ys)) if center_ys else vw / 2.0
print(f"  centerY: {center_y:.1f}px (averaged over {len(center_ys)} detected/corrected lines), "
      f"vw={vw}, period={period:.2f}s  (informational -- not stored in the file)")

polished_lines = {i: line_from_angle(a, center_y, vw) for i, a in enumerate(polished)}
save_corrections(out_path, polished_lines)

print(f"\nDone. Saved to:\n  {out_path}")
