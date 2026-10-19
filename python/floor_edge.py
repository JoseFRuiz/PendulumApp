import argparse
import cv2
import numpy as np
import os

from floor_detection import (FloorEdgeDetector, apply_corrections, line_angle_deg, load_corrections,
                              render_curve_panel)

try:
    import matplotlib.pyplot as plt
    _HAVE_MPL = True
except ImportError:
    _HAVE_MPL = False

Y_PLOT_MIN        = -60.0 # angle axis lower bound for the side curve panel (degrees)
Y_PLOT_MAX        =  60.0 # angle axis upper bound

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(
    description="Generate a video with the detected floor edge and its angle overlaid per frame."
)
parser.add_argument("input_file", nargs="?", default="baile_pendulo.mp4",
                    help="Input video filename in the same folder (default: baile_pendulo.mp4)")
parser.add_argument("--reference", default=None,
                    help="Use this corrections-shaped JSON ({frame_index: [x1,y1,x2,y2]}, one entry "
                         "per frame -- e.g. <stem>_floor_edge_polished.json from polish_floor_edge.py, "
                         "or a hand-edited copy of it, see edit_floor_edge.py --corrections) as the "
                         "video's line/curve/angle-label instead of the raw detection/corrections -- "
                         "not a comparison, a full swap. Requires a second pass over the video since "
                         "the curve panel grows the reference curve frame by frame.")
args = parser.parse_args()

input_path  = os.path.join(SCRIPT_DIR, args.input_file)
stem        = os.path.splitext(os.path.basename(args.input_file))[0]
output_path = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge.mp4")
plot_path   = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_angle.png")
corr_path   = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_corrections.json")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
vw           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vh           = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

LINE_COLOR            = (0, 0, 255)    # red -- raw detection/corrections
REFERENCE_LINE_COLOR  = (60, 170, 0)   # green -- a --reference track

if args.reference:
    # A reference file already has one line per frame -- running detection just
    # to immediately throw its result away would be pure waste, so it's skipped
    # entirely rather than run and then overridden.
    reference_path = os.path.join(SCRIPT_DIR, args.reference)
    reference = load_corrections(reference_path)
    if not reference:
        raise SystemExit(f"--reference {args.reference} not found or empty: {reference_path}")
    n = len(reference)
    print(f"--reference given: {reference_path} ({n} entries) -- skipping raw detection entirely")
    # apply_corrections, reused: a reference file is shaped exactly like a
    # corrections file (one line per frame -- see polish_floor_edge.py), so the
    # same function that overlays manual corrections fills in both arrays here.
    angle_history, line_history = apply_corrections([None] * n, [None] * n, reference)
    total_frames  = n
    draw_color    = REFERENCE_LINE_COLOR
    series_color  = REFERENCE_LINE_COLOR
    series_label  = "reference"
    cap.release()
else:
    corrections = load_corrections(corr_path)
    if corrections:
        print(f"Applying {len(corrections)} manual correction(s) from {corr_path} "
              "(see edit_floor_edge.py)")
    else:
        print(f"No manual corrections found at {corr_path}")
    print("No --reference given: running raw detection")

    # --- Pass 1: detect, applying corrections, and remember enough per frame
    # (line, angle) to redraw it in pass 2 without re-running detection. ---
    detector      = FloorEdgeDetector(vw, vh)
    angle_history = []   # smoothed angle (float) or None, one entry per frame
    line_history  = []   # best_line (post-correction), one entry per frame
    frame_number  = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        smoothed_angle, best_line, _lines = detector.process_frame(frame)

        if frame_number in corrections:
            best_line = corrections[frame_number]
            smoothed_angle = line_angle_deg(*best_line)

        angle_history.append(smoothed_angle)
        line_history.append(best_line)
        frame_number += 1

        if frame_number % int(fps) == 0:
            pct = 100 * frame_number // total_frames if total_frames > 0 else 0
            print(f"  [detect] {frame_number}/{total_frames} frames  ({pct}%)")

    cap.release()
    draw_color   = LINE_COLOR
    series_color = (30, 120, 220)
    series_label = "floor edge angle"

# --- Pass 2: redraw each frame with its (already-known) line/angle -- from
# detection+corrections, or loaded whole from --reference -- and write the
# output video. ---
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(output_path, fourcc, fps, (vw * 2, vh))
cap2 = cv2.VideoCapture(input_path)

frame_number = 0
while frame_number < len(angle_history):
    ret, frame = cap2.read()
    if not ret:
        print(f"  Warning: video ran out at frame {frame_number}, {len(angle_history)} expected "
              f"from {'the --reference file' if args.reference else 'detection'}.")
        break

    result = frame.copy()
    smoothed_angle = angle_history[frame_number]
    draw_line      = line_history[frame_number]

    if draw_line is not None:
        x1, y1, x2, y2 = draw_line
        cv2.line(result, (x1, y1), (x2, y2), draw_color, 3)

    if smoothed_angle is not None:
        label = f"{smoothed_angle:.1f} deg"
        font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2
        cv2.putText(result, label, (10, 40), font, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
        cv2.putText(result, label, (10, 40), font, scale, (255, 255, 255), thick, cv2.LINE_AA)

    series = [{"history": angle_history[:frame_number + 1], "color": series_color,
               "label": series_label}]
    curve_panel = render_curve_panel(series, fps, total_frames, vw, vh,
                                      y_min=Y_PLOT_MIN, y_max=Y_PLOT_MAX)
    combined    = np.concatenate([result, curve_panel], axis=1)
    out.write(combined)
    frame_number += 1

    if frame_number % int(fps) == 0:
        pct = 100 * frame_number // total_frames if total_frames > 0 else 0
        print(f"  [render] {frame_number}/{total_frames} frames  ({pct}%)")

cap2.release()
out.release()

# Build time / angle arrays
times  = [i / fps for i in range(len(angle_history))]
angles = [a if a is not None else float("nan") for a in angle_history]

# --- Signal statistics (period, max/min peaks) ---
angle_arr = np.array(angles)
time_arr  = np.array(times)
valid_mask = ~np.isnan(angle_arr)

est_period = est_max = est_min = None

if valid_mask.sum() > int(fps * 3):        # need at least 3 s of good data
    a_valid = angle_arr[valid_mask]

    # Period: FFT on the valid samples, pick the dominant non-DC frequency.
    # Gaps are treated as uniformly sampled — good enough when gaps are short.
    fft_mag = np.abs(np.fft.rfft(a_valid - a_valid.mean()))
    freqs   = np.fft.rfftfreq(len(a_valid), d=1.0 / fps)
    peak_f  = freqs[np.argmax(fft_mag[1:]) + 1]   # [1:] skips DC
    if peak_f > 0:
        est_period = 1.0 / peak_f

    # Peak / trough values: smooth over ~0.2 s, then find sign-changes in derivative.
    w      = max(3, int(fps * 0.2))
    smooth = np.convolve(a_valid, np.ones(w) / w, mode="same")
    d      = np.diff(smooth)
    max_idx = np.where((d[:-1] > 0) & (d[1:] <= 0))[0] + 1
    min_idx = np.where((d[:-1] < 0) & (d[1:] >= 0))[0] + 1

    # Median over all found peaks/troughs so that a few bad frames don't skew the estimate
    if len(max_idx):
        est_max = float(np.median(a_valid[max_idx]))
    if len(min_idx):
        est_min = float(np.median(a_valid[min_idx]))

# Print summary to console (ASCII only: Windows consoles may not be UTF-8)
parts = []
if est_period is not None: parts.append(f"period ~ {est_period:.2f} s")
if est_max    is not None: parts.append(f"max ~ {est_max:.1f} deg")
if est_min    is not None: parts.append(f"min ~ {est_min:.1f} deg")
if parts:
    print("  Signal: " + ",  ".join(parts))

if _HAVE_MPL:
    title = "Floor edge angle vs time"
    if parts:
        title += "   |   " + "   ".join(parts)

    fig, ax = plt.subplots(figsize=(10, 4))
    plot_color = "#3fa34d" if args.reference else "#1e78d4"
    ax.plot(times, angles, color=plot_color, linewidth=1.4, label=series_label)
    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    if est_max is not None:
        ax.axhline(est_max, color="#d94f4f", linewidth=0.9, linestyle="--",
                   label=f"max peak ≈ {est_max:.1f}°")
    if est_min is not None:
        ax.axhline(est_min, color="#4f7fd9", linewidth=0.9, linestyle="--",
                   label=f"min peak ≈ {est_min:.1f}°")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Angle (degrees)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)
    print(f"\nDone.\n  Video : {output_path}\n  Plot  : {plot_path}")
else:
    print(f"\nDone.\n  Video : {output_path}")
    print("  (install matplotlib to also save the angle plot)")
