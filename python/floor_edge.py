import argparse
from collections import deque
import cv2
import numpy as np
import os

try:
    import matplotlib.pyplot as plt
    _HAVE_MPL = True
except ImportError:
    _HAVE_MPL = False

# --- Tunable parameters ---
DILATE_KERNEL     = 60    # pixels to expand the person mask before removing their edges
CANNY_LOW         = 15    # Canny lower threshold
CANNY_HIGH        = 50    # Canny upper threshold
HOUGH_THRESHOLD   = 20    # minimum Hough votes
MIN_LINE_FRAC     = 6     # minimum line length = frame_width / this value
MAX_LINE_GAP      = 60    # maximum gap between collinear segments to merge
PERSON_THRESH_MIN    = 50  # minimum Otsu value to consider a person present
PERSON_BRIGHT_THRESH = 180 # fixed upper threshold: pixels brighter than this are white clothes.
                           # Used instead of Otsu's mask so that the medium-brightness floor
                           # is never included in the person hull even when the person fills
                           # most of the frame and Otsu's adaptive threshold drops too low.
FLOOR_DARK_LOW    = 5     # } dual threshold that isolates the floor's brightness band:
FLOOR_DARK_HIGH   = 25    # } pixels outside [LOW, HIGH] are excluded before Canny.
                          # The floor is dark-but-not-black (5–25); person's white clothes
                          # are above HIGH (→ zeroed); black background is below LOW (→ zeroed).
FLOOR_Y_MIN       = 0.45  # floor line midpoint must be below this fraction of frame height
FLOOR_MIN_SPAN    = 0.20  # winning line must span at least this fraction of frame width
MAX_FLOOR_ANGLE   = 40.0  # reject angles steeper than this (filters near-vertical body edges)
ANGLE_BUCKET_DEG   = 5.0  # bucket width for angle-cluster voting (degrees)
MIN_CLUSTER_VOTES  = 2    # winning cluster needs at least this many supporting lines;
                          # a single isolated body edge can never win alone
MIN_TOTAL_SPAN_FRAC = 0.5 # all segments in the winning cluster combined must cover at least
                          # this fraction of frame width; floor fragments add up, body edges don't
SMOOTH_WINDOW      = 7    # rolling-median window (smaller is OK with stricter admission gates)

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
min_line_len = vw // MIN_LINE_FRAC

kernel = np.ones((DILATE_KERNEL, DILATE_KERNEL), np.uint8)

# Output video is twice as wide: left = edge detection, right = angle-vs-time curve
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(output_path, fourcc, fps, (vw * 2, vh))


def render_curve_panel(history, fps, total_frames, panel_w, panel_h):
    """Render the angle-vs-time curve onto a numpy image (panel_w × panel_h, BGR)."""
    panel = np.full((panel_h, panel_w, 3), 245, dtype=np.uint8)

    ml, mr, mt, mb = 55, 15, 20, 35
    pw = panel_w - ml - mr
    ph = panel_h - mt - mb
    y_span  = Y_PLOT_MAX - Y_PLOT_MIN
    n_total = max(total_frames - 1, 1)

    def to_px(frame_idx, angle):
        x = ml + int(pw * frame_idx / n_total)
        y = mt + int(ph * (Y_PLOT_MAX - angle) / y_span)
        return x, max(mt, min(mt + ph, y))

    cv2.rectangle(panel, (ml, mt), (ml + pw, mt + ph), (225, 225, 225), cv2.FILLED)
    cv2.rectangle(panel, (ml, mt), (ml + pw, mt + ph), (120, 120, 120), 1)

    for a in range(int(Y_PLOT_MIN), int(Y_PLOT_MAX) + 1, 10):
        _, py = to_px(0, a)
        grid_color = (200, 200, 200) if a != 0 else (160, 160, 160)
        cv2.line(panel, (ml, py), (ml + pw, py), grid_color, 1)
        cv2.putText(panel, f"{a:+d}", (2, py + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (60, 60, 60), 1, cv2.LINE_AA)

    prev_pt = None
    for i, angle in enumerate(history):
        if angle is None:
            prev_pt = None
            continue
        pt = to_px(i, angle)
        if prev_pt is not None:
            cv2.line(panel, prev_pt, pt, (30, 120, 220), 2)
        prev_pt = pt

    n = len(history)
    if n > 0:
        cx, _ = to_px(n - 1, 0)
        cv2.line(panel, (cx, mt), (cx, mt + ph), (0, 0, 180), 1)

    for i in range(7):
        fi    = int(total_frames * i / 6)
        tx, _ = to_px(fi, Y_PLOT_MIN)
        cv2.line(panel, (tx, mt + ph), (tx, mt + ph + 4), (120, 120, 120), 1)
        cv2.putText(panel, f"{fi / fps:.0f}s", (tx - 10, mt + ph + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (60, 60, 60), 1, cv2.LINE_AA)

    cv2.putText(panel, "Angle (deg) vs Time", (ml, mt - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)

    return panel


# raw_history holds the last SMOOTH_WINDOW valid raw angle detections.
# smoothed_angle is their median — much more resistant to outliers than EMA.
raw_history   = deque(maxlen=SMOOTH_WINDOW)
smoothed_angle = None
angle_history  = []   # smoothed angle (float) or None, one entry per output frame
frame_number   = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Build person mask only when a bright subject is actually present.
    otsu_val, person_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    hull_filled = np.zeros_like(gray)
    if otsu_val >= PERSON_THRESH_MIN:
        # Use a fixed bright threshold to identify white-clothes pixels precisely.
        # Otsu's adaptive threshold can drop when the person fills the frame, causing
        # it to include the medium-brightness floor in the mask.  A fixed threshold
        # at PERSON_BRIGHT_THRESH captures only the bright white clothing, so the
        # global hull never extends down to cover the floor edge.
        _, bright_mask = cv2.threshold(gray, PERSON_BRIGHT_THRESH, 255, cv2.THRESH_BINARY)
        contours, _    = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            all_pts     = np.vstack([cnt.reshape(-1, 2) for cnt in contours])
            global_hull = cv2.convexHull(all_pts)
            cv2.fillPoly(hull_filled, [global_hull], 255)
    person_dilated = cv2.dilate(hull_filled, kernel)

    # Isolate the floor brightness zone before running Canny.
    # THRESH_TOZERO_INV zeroes pixels above FLOOR_DARK_HIGH (white clothes, bright areas).
    # The second threshold removes pixels below FLOOR_DARK_LOW (black background).
    # Result: only the medium-dark floor pixels remain, so Canny sees the floor boundary
    # directly rather than having to filter out the person after the fact.
    floor_zone  = cv2.threshold(gray, FLOOR_DARK_HIGH, 255, cv2.THRESH_TOZERO_INV)[1]
    floor_zone  = cv2.threshold(floor_zone, FLOOR_DARK_LOW, 255, cv2.THRESH_BINARY)[1]

    edges       = cv2.Canny(floor_zone, CANNY_LOW, CANNY_HIGH)
    # The person's silhouette outline (where white→black transition passes through 5–25)
    # still appears in floor_zone; the hull mask removes it.
    edges_floor = cv2.bitwise_and(edges, cv2.bitwise_not(person_dilated))

    lines = cv2.HoughLinesP(edges_floor, 1, np.pi / 180,
                             threshold=HOUGH_THRESHOLD,
                             minLineLength=min_line_len,
                             maxLineGap=MAX_LINE_GAP)

    result = frame.copy()

    if lines is not None:
        # Draw all Hough candidates in dim blue
        for seg in lines:
            sx1, sy1, sx2, sy2 = seg[0]
            cv2.line(result, (sx1, sy1), (sx2, sy2), (180, 80, 0), 1)

        # Spatial pre-filter: keep lines whose midpoint is in the lower part of the frame
        floor_lines = [l for l in lines if (l[0][1] + l[0][3]) / 2 >= vh * FLOOR_Y_MIN]
        candidates  = floor_lines if floor_lines else lines

        # Angle-cluster voting:
        # Bucket all candidate lines by their angle (5° bins, capped at ±MAX_FLOOR_ANGLE).
        # The floor edge fragments all land in the same bucket; isolated body edges scatter.
        # The bucket with the most supporting segments wins.
        angle_buckets = {}
        for l in candidates:
            lx1, ly1, lx2, ly2 = l[0]
            a = np.degrees(np.arctan2(-(ly2 - ly1), lx2 - lx1))
            if a > 90:     a -= 180
            elif a <= -90: a += 180
            if abs(a) > MAX_FLOOR_ANGLE:
                continue
            b = round(a / ANGLE_BUCKET_DEG) * ANGLE_BUCKET_DEG
            angle_buckets.setdefault(b, []).append(l)

        if angle_buckets:
            def _cluster_score(b):
                segs       = angle_buckets[b]
                count      = len(segs)
                total_span = sum(np.hypot(l[0][2] - l[0][0], l[0][3] - l[0][1]) for l in segs)
                # Continuity bias: small nudge toward the angle we already trust.
                # Weak (0–0.4 votes) so vote count dominates; only breaks near-ties.
                if smoothed_angle is not None:
                    proximity = max(0.0, 1.0 - abs(b - smoothed_angle) / MAX_FLOOR_ANGLE)
                else:
                    proximity = 0.0
                return (count + 0.4 * proximity, total_span)

            best_bucket  = max(angle_buckets, key=_cluster_score)
            bucket_lines = angle_buckets[best_bucket]

            # Representative line = longest segment in the winning cluster
            best = max(bucket_lines,
                       key=lambda l: np.hypot(l[0][2] - l[0][0], l[0][3] - l[0][1]))[0]
            x1, y1, x2, y2 = best
            cv2.line(result, (x1, y1), (x2, y2), (0, 0, 255), 3)

            # Quality gates before updating the raw-angle history:
            # 1. The cluster must have enough supporting lines (not a lone stray edge).
            # 2. Combined span of all cluster segments must be significant (floor fragments
            #    add up to wide coverage; isolated body edges are short and sparse).
            total_cluster_span = sum(
                np.hypot(l[0][2] - l[0][0], l[0][3] - l[0][1]) for l in bucket_lines)
            span_ok   = np.hypot(x2 - x1, y2 - y1) / vw >= FLOOR_MIN_SPAN
            votes_ok  = len(bucket_lines) >= MIN_CLUSTER_VOTES
            cluster_ok = total_cluster_span >= vw * MIN_TOTAL_SPAN_FRAC

            if span_ok and (votes_ok or cluster_ok):
                raw_angle = np.degrees(np.arctan2(-(y2 - y1), x2 - x1))
                if raw_angle > 90:     raw_angle -= 180
                elif raw_angle <= -90: raw_angle += 180
                raw_history.append(raw_angle)

    # Smoothed angle = median of recent valid detections (robust to ~50% bad frames)
    smoothed_angle = float(np.median(raw_history)) if raw_history else None
    angle_history.append(smoothed_angle)

    if smoothed_angle is not None:
        label = f"{smoothed_angle:.1f} deg"
        font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2
        cv2.putText(result, label, (10, 40), font, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
        cv2.putText(result, label, (10, 40), font, scale, (255, 255, 255), thick, cv2.LINE_AA)

    curve_panel = render_curve_panel(angle_history, fps, total_frames, vw, vh)
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

# Print summary to console
parts = []
if est_period is not None: parts.append(f"period ≈ {est_period:.2f} s")
if est_max    is not None: parts.append(f"max ≈ {est_max:.1f}°")
if est_min    is not None: parts.append(f"min ≈ {est_min:.1f}°")
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
