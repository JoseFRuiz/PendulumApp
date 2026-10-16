# Run: python edit_floor_edge.py baile_pendulo.mp4

"""Semi-automatic floor-edge editor: review and manually correct per-frame floor-edge
detections, frame by frame, for videos where the automatic detector (floor_detection.py)
gets it wrong -- picks the wrong line, or finds no line at all.

Usage:
  python edit_floor_edge.py baile_pendulo.mp4

  Afterwards, run whichever of these you actually need against the same video --
  all three automatically pick up the saved corrections (see "Corrections" below),
  there's no flag to pass:
    python floor_edge.py baile_pendulo.mp4          # regenerate the preview video +
                                                      # angle plot, to visually confirm
                                                      # the corrections look right
                                                      # (corrected frames draw magenta,
                                                      # not red)
    python pendulum_sim.py baile_pendulo.mp4         # regenerate the PC-side
                                                      # installation-effect preview
    python export_angle_track.py <source_video>.mp4  # regenerate the JSON actually
                                                      # bundled into the Android app --
                                                      # this is the one that matters for
                                                      # the real installation; see
                                                      # CLAUDE.md's "Bundled video asset"

Controls:
  Right / D       next frame
  Left  / A       previous frame
  N               jump to next flagged frame (no detection, or a big jump -- likely wrong line)
  P               jump to previous flagged frame
  Click and drag  draw a new line for the current frame (auto-extended to the full width)
  R               revert current frame to the automatic detection (discard manual correction)
  S               save corrections now
  Q / Esc         save and quit

Corrections are saved to <stem>_floor_edge_corrections.json next to the input video, and
automatically picked up by floor_edge.py, pendulum_sim.py, and export_angle_track.py the
next time they run against the same video (see floor_detection.load_corrections/apply_corrections).

Detection itself can be slow for long videos, so results are cached to
<stem>_floor_edge_detection_cache.json after the first run and reused on subsequent runs.
Pass --redetect to force a fresh detection pass (needed after any change to
floor_detection.py's detection algorithm, since a stale cache would silently keep using the
old results).
"""

import argparse
import json
import os

import cv2
import numpy as np

from floor_detection import (
    FloorEdgeDetector, extend_two_points, line_angle_deg,
    load_corrections, save_corrections,
)

OUTLIER_JUMP_DEG = 8.0  # a raw-angle jump bigger than this from the previous valid
                        # detection is treated as "probably picked the wrong line"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("input_file", nargs="?", default="baile_pendulo.mp4",
                    help="Input video filename in the same folder (default: baile_pendulo.mp4)")
parser.add_argument("--redetect", action="store_true",
                    help="Force a fresh detection pass instead of using a cached one.")
args = parser.parse_args()

input_path        = os.path.join(SCRIPT_DIR, args.input_file)
stem              = os.path.splitext(os.path.basename(args.input_file))[0]
cache_path        = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_detection_cache.json")
corrections_path  = os.path.join(SCRIPT_DIR, f"{stem}_floor_edge_corrections.json")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

vw           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vh           = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps          = cap.get(cv2.CAP_PROP_FPS) or 30
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))


def run_detection():
    print("Detecting floor edge angle (this can take a while)...")
    detector = FloorEdgeDetector(vw, vh)
    raw_angles, lines_raw = [], []
    i = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        angle, best_line, _ = detector.process_frame(frame)
        raw_angles.append(angle)
        lines_raw.append(best_line)
        i += 1
        if i % int(fps) == 0:
            pct = 100 * i // total_frames if total_frames > 0 else 0
            print(f"  {i}/{total_frames} frames  ({pct}%)")
    return raw_angles, lines_raw


def load_cache():
    if args.redetect or not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path) as f:
            data = json.load(f)
        if data.get("sourceVideo") != args.input_file or data.get("frameCount") != total_frames:
            return None
        raw_angles = data["rawAngles"]
        lines_raw  = [tuple(l) if l is not None else None for l in data["linesRaw"]]
        return raw_angles, lines_raw
    except Exception:
        return None


def save_cache(raw_angles, lines_raw):
    data = {
        "sourceVideo": args.input_file,
        "frameCount": total_frames,
        "rawAngles": raw_angles,
        "linesRaw": [list(map(int, l)) if l is not None else None for l in lines_raw],
    }
    with open(cache_path, "w") as f:
        json.dump(data, f)


cached = load_cache()
if cached is not None:
    raw_angles, lines_raw = cached
    print(f"Using cached detection from {cache_path} ({len(raw_angles)} frames).")
    print("  Pass --redetect to force a fresh pass (needed after detection-algorithm changes).")
else:
    raw_angles, lines_raw = run_detection()
    save_cache(raw_angles, lines_raw)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

n = len(raw_angles)
corrections = load_corrections(corrections_path)
if corrections:
    print(f"Loaded {len(corrections)} existing manual correction(s) from {corrections_path}")
else:
    print("No existing manual corrections.")


def is_flagged(i):
    """A frame needs review if detection failed outright, or if it succeeded but
    jumped suspiciously far from the previous valid detection (probably picked the
    wrong line -- a body edge instead of the floor, say). Based on the original
    auto-detection only, regardless of any manual correction already applied."""
    if raw_angles[i] is None:
        return True
    j = i - 1
    while j >= 0 and raw_angles[j] is None:
        j -= 1
    if j < 0:
        return False
    return abs(raw_angles[i] - raw_angles[j]) > OUTLIER_JUMP_DEG


def needs_review(i):
    """Still-outstanding work: flagged AND not already manually corrected this session."""
    return is_flagged(i) and i not in corrections


# Only re-seek/re-read the video when the displayed frame index actually changes --
# render() gets called on every loop tick (for live drag feedback), so this avoids
# re-decoding the same frame dozens of times per second while idling on one frame.
frame_cache = {"idx": None, "img": None}


def get_frame(i):
    if frame_cache["idx"] != i:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, img = cap.read()
        frame_cache["idx"] = i
        frame_cache["img"] = img if ret else np.zeros((vh, vw, 3), dtype=np.uint8)
    return frame_cache["img"]


WINDOW = "edit_floor_edge -- see console for controls"
cv2.namedWindow(WINDOW)

state = {"idx": 0, "drag_start": None, "drag_now": None}


def on_mouse(event, x, y, flags, userdata):
    if event == cv2.EVENT_LBUTTONDOWN:
        state["drag_start"] = (x, y)
        state["drag_now"] = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and state["drag_start"] is not None:
        state["drag_now"] = (x, y)
    elif event == cv2.EVENT_LBUTTONUP and state["drag_start"] is not None:
        x1, y1 = state["drag_start"]
        x2, y2 = x, y
        state["drag_start"] = None
        state["drag_now"] = None
        if (x1, y1) != (x2, y2):
            line = extend_two_points(x1, y1, x2, y2, vw)
            if line is not None:
                corrections[state["idx"]] = line


cv2.setMouseCallback(WINDOW, on_mouse)


def render():
    i = state["idx"]
    img = get_frame(i).copy()

    if i in corrections:
        line, color, status = corrections[i], (255, 0, 255), "MANUAL"
    elif lines_raw[i] is not None:
        if raw_angles[i] is not None:
            line, color, status = lines_raw[i], (0, 200, 0), "auto (trusted)"
        else:
            line, color, status = lines_raw[i], (0, 165, 255), "auto (rejected by quality gates)"
    else:
        line, color, status = None, None, "NO DETECTION"

    if line is not None:
        x1, y1, x2, y2 = line
        cv2.line(img, (int(x1), int(y1)), (int(x2), int(y2)), color, 3)

    if state["drag_start"] is not None and state["drag_now"] is not None:
        cv2.line(img, state["drag_start"], state["drag_now"], (255, 255, 255), 1, cv2.LINE_AA)

    angle_text = f"{line_angle_deg(*line):+.1f} deg" if line is not None else "--"
    flag_text = "FLAGGED" if is_flagged(i) else "ok"
    header = f"frame {i}/{n - 1}  t={i / fps:.2f}s  angle={angle_text}  [{status}]  {flag_text}"
    cv2.putText(img, header, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, header, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)

    help_text = ("arrows/AD: step  N/P: next/prev flagged  drag: redraw line  "
                 "R: revert  S: save  Q: save+quit")
    cv2.putText(img, help_text, (10, vh - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, help_text, (10, vh - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.imshow(WINDOW, img)


n_outstanding = sum(1 for i in range(n) if needs_review(i))
print(f"\n{n_outstanding} frame(s) still need review (out of {n} total). "
      "Press N to jump to the first one.\n")
print(__doc__)

while True:
    render()
    # Always a short poll (never a blocking waitKey(0)): a click-drag involves no
    # keypress at all, so a blocking wait would freeze the live preview mid-drag and
    # the just-finalized line wouldn't appear until some unrelated key was pressed.
    key = cv2.waitKeyEx(30)
    if key == -1:
        continue  # just a redraw tick, no key pressed

    if key in (ord('q'), ord('Q'), 27):
        save_corrections(corrections_path, corrections)
        print(f"Saved {len(corrections)} correction(s) to {corrections_path}")
        break
    elif key in (ord('s'), ord('S')):
        save_corrections(corrections_path, corrections)
        print(f"Saved {len(corrections)} correction(s) to {corrections_path}")
    elif key in (ord('r'), ord('R')):
        corrections.pop(state["idx"], None)
    elif key in (ord('d'), ord('D'), 2555904, 65363):  # right arrow (Win / Linux+macOS)
        state["idx"] = min(n - 1, state["idx"] + 1)
    elif key in (ord('a'), ord('A'), 2424832, 65361):  # left arrow (Win / Linux+macOS)
        state["idx"] = max(0, state["idx"] - 1)
    elif key in (ord('n'), ord('N')):
        j = state["idx"] + 1
        while j < n and not needs_review(j):
            j += 1
        if j < n:
            state["idx"] = j
        else:
            print("No more flagged frames ahead.")
    elif key in (ord('p'), ord('P')):
        j = state["idx"] - 1
        while j >= 0 and not needs_review(j):
            j -= 1
        if j >= 0:
            state["idx"] = j
        else:
            print("No flagged frames behind.")

cap.release()
cv2.destroyAllWindows()
