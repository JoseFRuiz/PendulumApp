import cv2
import os

INPUT_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baile_pendulo.mp4")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baile_pendulo_colored.mp4")

TINT_DURATION = 0.1  # seconds of color tint at the start of each second

cap = cv2.VideoCapture(INPUT_FILE)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {INPUT_FILE}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(OUTPUT_FILE, fourcc, fps, (width, height))

frame_number = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break

    time_s             = frame_number / fps
    second             = int(time_s)
    fraction_in_second = time_s - second

    if fraction_in_second < TINT_DURATION:
        # OpenCV stores pixels as BGR (Blue=0, Green=1, Red=2)
        frame = frame.copy()
        if second % 2 == 0:
            # Blue: keep channel 0 (B), zero out G and R
            frame[:, :, 1] = 0
            frame[:, :, 2] = 0
        else:
            # Red: keep channel 2 (R), zero out B and G
            frame[:, :, 0] = 0
            frame[:, :, 1] = 0

    out.write(frame)
    frame_number += 1

    if frame_number % int(fps) == 0:
        pct = 100 * frame_number // total_frames
        print(f"  {frame_number}/{total_frames} frames  ({pct}%)")

cap.release()
out.release()
print(f"\nDone. Saved to:\n  {OUTPUT_FILE}")
