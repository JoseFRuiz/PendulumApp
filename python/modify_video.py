import argparse
import cv2
import numpy as np
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(
    description="Generate a copy of a video with a modified start time and playback speed."
)
parser.add_argument("input_file", nargs="?", default="baile_pendulo.mp4",
                    help="Input video filename in the same folder (default: baile_pendulo.mp4)")
parser.add_argument("--start", type=float, default=0.0,
                    help="Start offset in seconds. "
                         "Positive: skip that many seconds from the video. "
                         "Negative: prepend that many seconds of fully white frames.")
parser.add_argument("--rate", type=float, default=1.0,
                    help="Playback speed rate (default 1.0; e.g. 0.9=slower, 1.1=faster)")
args = parser.parse_args()

rate      = max(0.01, args.rate)
start_sec = args.start

input_path  = os.path.join(SCRIPT_DIR, args.input_file)
stem        = os.path.splitext(os.path.basename(args.input_file))[0]
output_path = os.path.join(SCRIPT_DIR, f"{stem}_modified.mp4")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
vw           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vh           = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(output_path, fourcc, fps, (vw, vh))

# Prepend white frames when start is negative
n_white = round(abs(start_sec) * fps) if start_sec < 0 else 0
if n_white > 0:
    white = np.full((vh, vw, 3), 255, dtype=np.uint8)
    for _ in range(n_white):
        out.write(white)

# Seek into the video when start is positive
if start_sec > 0:
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(start_sec * fps))

# Bootstrap: read first two source frames
ret, frame_a = cap.read()
if not ret:
    cap.release()
    out.release()
    raise RuntimeError("No frames available at the requested start position.")

ret, frame_b = cap.read()
if not ret:
    frame_b = None
next_src_idx = 1  # frame_b is at this index relative to the seek point; frame_a is at 0

virtual_pos  = 0.0  # real-valued position in source-frame space (after the seek point)
frames_written = n_white
done = False
while not done:
    src_int = int(virtual_pos)
    alpha   = virtual_pos - src_int

    # Advance the source window until frame_a sits at src_int
    while next_src_idx - 1 < src_int:
        if frame_b is None:
            done = True
            break
        frame_a = frame_b
        ret, frame_b = cap.read()
        if not ret:
            frame_b = None
        next_src_idx += 1

    if done:
        break

    # Blend adjacent source frames for smooth speed changes
    if alpha > 0 and frame_b is not None:
        result = cv2.addWeighted(frame_a, 1.0 - alpha, frame_b, alpha, 0)
    else:
        result = frame_a

    out.write(result)
    frames_written += 1
    virtual_pos += rate

    if frames_written % int(fps) == 0:
        src_pos = src_int + (round(start_sec * fps) if start_sec > 0 else 0)
        pct = 100 * src_pos // total_frames if total_frames > 0 else 0
        print(f"  output frame {frames_written}  (source {src_pos}/{total_frames}, {pct}%)")

cap.release()
out.release()
print(f"\nDone. Saved to:\n  {output_path}")
