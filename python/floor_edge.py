import argparse
import cv2
import numpy as np
import os

from floor_detection import FloorEdgeDetector, render_curve_panel

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
args = parser.parse_args()

input_path  = os.path.join(SCRIPT_DIR, args.input_file)
stem        = os.path.splitext(os.path.basename(args.input_file))[0]
output_path = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge.mp4")
plot_path   = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_angle.png")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
vw           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vh           = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# Output video is twice as wide: left = edge detection, right = angle-vs-time curve
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(output_path, fourcc, fps, (vw * 2, vh))


detector      = FloorEdgeDetector(vw, vh)
angle_history = []   # smoothed angle (float) or None, one entry per output frame
frame_number  = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    smoothed_angle, best_line, lines = detector.process_frame(frame)
    angle_history.append(smoothed_angle)

    result = frame.copy()

    if lines is not None:
        # Draw all Hough candidates in dim blue
        for seg in lines:
            sx1, sy1, sx2, sy2 = seg[0]
            cv2.line(result, (sx1, sy1), (sx2, sy2), (180, 80, 0), 1)

    if best_line is not None:
        x1, y1, x2, y2 = best_line
        cv2.line(result, (x1, y1), (x2, y2), (0, 0, 255), 3)

    if smoothed_angle is not None:
        label = f"{smoothed_angle:.1f} deg"
        font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2
        cv2.putText(result, label, (10, 40), font, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
        cv2.putText(result, label, (10, 40), font, scale, (255, 255, 255), thick, cv2.LINE_AA)

    curve_panel = render_curve_panel(
        [{"history": angle_history, "color": (30, 120, 220), "label": "floor edge angle"}],
        fps, total_frames, vw, vh, y_min=Y_PLOT_MIN, y_max=Y_PLOT_MAX)
    combined    = np.concatenate([result, curve_panel], axis=1)
    out.write(combined)
    frame_number += 1

    if frame_number % int(fps) == 0:
        pct = 100 * frame_number // total_frames if total_frames > 0 else 0
        print(f"  {frame_number}/{total_frames} frames  ({pct}%)")

cap.release()
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
    ax.plot(times, angles, color="#1e78d4", linewidth=1.2, label="angle")
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
    if est_max is not None or est_min is not None:
        ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)
    print(f"\nDone.\n  Video : {output_path}\n  Plot  : {plot_path}")
else:
    print(f"\nDone.\n  Video : {output_path}")
    print("  (install matplotlib to also save the angle plot)")
