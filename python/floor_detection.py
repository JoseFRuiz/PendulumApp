"""Shared floor-edge angle detection, used by floor_edge.py and pendulum_sim.py."""

from collections import deque
import cv2
import numpy as np

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


class FloorEdgeDetector:
    """Per-frame floor-edge angle detector. Feed frames in order via process_frame()."""

    def __init__(self, frame_width, frame_height):
        self.vw = frame_width
        self.vh = frame_height
        self.min_line_len = frame_width // MIN_LINE_FRAC
        self.kernel = np.ones((DILATE_KERNEL, DILATE_KERNEL), np.uint8)
        self.raw_history = deque(maxlen=SMOOTH_WINDOW)
        self.smoothed_angle = None

    def process_frame(self, frame):
        """Update detector state with one frame; return (smoothed_angle, best_line, lines).

        smoothed_angle is the running median angle in degrees, or None if no valid
        detection has been made yet. best_line is (x1, y1, x2, y2) for the winning
        segment this frame, or None if no line was selected this frame. lines is the
        raw Hough candidate array for this frame (or None), useful for debug overlays.
        """
        vh, vw = self.vh, self.vw
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Build person mask only when a bright subject is actually present.
        otsu_val, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
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
        person_dilated = cv2.dilate(hull_filled, self.kernel)

        # Isolate the floor brightness zone before running Canny.
        floor_zone  = cv2.threshold(gray, FLOOR_DARK_HIGH, 255, cv2.THRESH_TOZERO_INV)[1]
        floor_zone  = cv2.threshold(floor_zone, FLOOR_DARK_LOW, 255, cv2.THRESH_BINARY)[1]

        edges       = cv2.Canny(floor_zone, CANNY_LOW, CANNY_HIGH)
        edges_floor = cv2.bitwise_and(edges, cv2.bitwise_not(person_dilated))

        lines = cv2.HoughLinesP(edges_floor, 1, np.pi / 180,
                                 threshold=HOUGH_THRESHOLD,
                                 minLineLength=self.min_line_len,
                                 maxLineGap=MAX_LINE_GAP)
        if lines is not None:
            # Normalize to the classic (N, 1, 4) shape: some OpenCV versions (e.g. 5.x)
            # return (N, 4) instead, which breaks the l[0]-style indexing used below.
            lines = lines.reshape(-1, 1, 4)

        best_line = None

        if lines is not None:
            # Spatial pre-filter: keep lines whose midpoint is in the lower part of the frame
            floor_lines = [l for l in lines if (l[0][1] + l[0][3]) / 2 >= vh * FLOOR_Y_MIN]
            candidates  = floor_lines if floor_lines else lines

            # Angle-cluster voting: bucket candidate lines by angle (5° bins), the bucket
            # with the most supporting segments wins (floor fragments cluster; body edges scatter).
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
                    if self.smoothed_angle is not None:
                        proximity = max(0.0, 1.0 - abs(b - self.smoothed_angle) / MAX_FLOOR_ANGLE)
                    else:
                        proximity = 0.0
                    return (count + 0.4 * proximity, total_span)

                best_bucket  = max(angle_buckets, key=_cluster_score)
                bucket_lines = angle_buckets[best_bucket]

                # Representative line = longest segment in the winning cluster
                best = max(bucket_lines,
                           key=lambda l: np.hypot(l[0][2] - l[0][0], l[0][3] - l[0][1]))[0]
                x1, y1, x2, y2 = best
                best_line = (x1, y1, x2, y2)

                # Quality gates before updating the raw-angle history.
                total_cluster_span = sum(
                    np.hypot(l[0][2] - l[0][0], l[0][3] - l[0][1]) for l in bucket_lines)
                span_ok    = np.hypot(x2 - x1, y2 - y1) / vw >= FLOOR_MIN_SPAN
                votes_ok   = len(bucket_lines) >= MIN_CLUSTER_VOTES
                cluster_ok = total_cluster_span >= vw * MIN_TOTAL_SPAN_FRAC

                if span_ok and (votes_ok or cluster_ok):
                    raw_angle = np.degrees(np.arctan2(-(y2 - y1), x2 - x1))
                    if raw_angle > 90:     raw_angle -= 180
                    elif raw_angle <= -90: raw_angle += 180
                    self.raw_history.append(raw_angle)

        # Smoothed angle = median of recent valid detections (robust to ~50% bad frames)
        self.smoothed_angle = float(np.median(self.raw_history)) if self.raw_history else None
        return self.smoothed_angle, best_line, lines


def detect_sequence(cap, progress_label=None):
    """Run the detector over every remaining frame of an opened VideoCapture.

    Returns a list of (smoothed_angle, best_line) tuples, one per frame, in read
    order (either element may be None). Does not release or rewind the capture.
    """
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    detector = FloorEdgeDetector(vw, vh)
    results = []
    frame_number = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        angle, best_line, _ = detector.process_frame(frame)
        results.append((angle, best_line))
        frame_number += 1
        if progress_label and frame_number % int(fps) == 0:
            pct = 100 * frame_number // total_frames if total_frames > 0 else 0
            print(f"  [{progress_label}] {frame_number}/{total_frames} frames  ({pct}%)")

    return results


def detect_angle_sequence(cap, progress_label=None):
    """Like detect_sequence(), but returns only the list of smoothed angles."""
    return [angle for angle, _ in detect_sequence(cap, progress_label)]


def render_curve_panel(series, fps, total_frames, panel_w, panel_h,
                        y_min=-60.0, y_max=60.0):
    """Render one or more angle-vs-time curves onto a numpy image (panel_w x panel_h, BGR).

    series is a list of {"history": [...], "color": (b, g, r), "label": str} dicts.
    Each history is a list of angle (float) or None, one entry per frame; None
    entries break the line (used to show detection gaps). For convenience, a bare
    list of angles is also accepted and treated as a single unlabeled series.
    """
    if series and not isinstance(series[0], dict):
        series = [{"history": series, "color": (30, 120, 220), "label": None}]

    panel = np.full((panel_h, panel_w, 3), 245, dtype=np.uint8)

    ml, mr, mt, mb = 55, 15, 20, 35
    pw = panel_w - ml - mr
    ph = panel_h - mt - mb
    y_span  = y_max - y_min
    n_total = max(total_frames - 1, 1)

    def to_px(frame_idx, angle):
        x = ml + int(pw * frame_idx / n_total)
        y = mt + int(ph * (y_max - angle) / y_span)
        return x, max(mt, min(mt + ph, y))

    cv2.rectangle(panel, (ml, mt), (ml + pw, mt + ph), (225, 225, 225), cv2.FILLED)
    cv2.rectangle(panel, (ml, mt), (ml + pw, mt + ph), (120, 120, 120), 1)

    for a in range(int(y_min), int(y_max) + 1, 10):
        _, py = to_px(0, a)
        grid_color = (200, 200, 200) if a != 0 else (160, 160, 160)
        cv2.line(panel, (ml, py), (ml + pw, py), grid_color, 1)
        cv2.putText(panel, f"{a:+d}", (2, py + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (60, 60, 60), 1, cv2.LINE_AA)

    max_len = 0
    for s in series:
        history   = s["history"]
        color     = s["color"]
        thickness = s.get("thickness", 2)
        max_len = max(max_len, len(history))
        prev_pt = None
        for i, angle in enumerate(history):
            if angle is None:
                prev_pt = None
                continue
            pt = to_px(i, angle)
            if prev_pt is not None:
                cv2.line(panel, prev_pt, pt, color, thickness)
            prev_pt = pt

    if max_len > 0:
        cx, _ = to_px(max_len - 1, 0)
        cv2.line(panel, (cx, mt), (cx, mt + ph), (0, 0, 180), 1)

    if any(s.get("label") for s in series):
        lx, ly = ml + 10, mt + 16
        for s in series:
            if not s.get("label"):
                continue
            cv2.line(panel, (lx, ly), (lx + 24, ly), s["color"], 2)
            cv2.putText(panel, s["label"], (lx + 30, ly + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 40), 1, cv2.LINE_AA)
            ly += 18

    for i in range(7):
        fi    = int(total_frames * i / 6)
        tx, _ = to_px(fi, y_min)
        cv2.line(panel, (tx, mt + ph), (tx, mt + ph + 4), (120, 120, 120), 1)
        cv2.putText(panel, f"{fi / fps:.0f}s", (tx - 10, mt + ph + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (60, 60, 60), 1, cv2.LINE_AA)

    cv2.putText(panel, "Angle (deg) vs Time", (ml, mt - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)

    return panel


def fill_gaps(angles):
    """Forward-fill None entries from the last valid angle, then back-fill any
    leading None entries from the first valid angle. Returns a new list with no
    None entries, or the original list if it contains no valid detections at all.
    """
    filled = list(angles)
    last_valid = None
    for i, a in enumerate(filled):
        if a is None:
            filled[i] = last_valid
        else:
            last_valid = a

    first_valid = next((a for a in filled if a is not None), None)
    if first_valid is None:
        return filled  # no valid detections anywhere

    for i, a in enumerate(filled):
        if a is None:
            filled[i] = first_valid
        else:
            break

    return filled
