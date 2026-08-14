#!/usr/bin/env python3
"""
prep_gif.py -- shrink a GIF until a badge can play it.

Runs on your computer, not on the badge. Needs Pillow (`pip install Pillow`).

    python3 prep_gif.py cat.gif -o gifs/cat.gif
    python3 prep_gif.py cat.gif --max-width 64 --colors 32 --keep-every 2

There are two different "too big" problems and they have different fixes,
so the report at the end prints both:

  RAM   `gifio.OnDiskGif` streams frames off the filesystem one at a time,
        so the number of frames and the file size cost you nothing at
        runtime. What costs RAM is ONE frame buffer:

            bytes = width * height * 2      (RGB565)

        The only way to reduce it is to make the picture smaller in
        pixels. The badge has 512 KB of SRAM, no PSRAM, and gifio refuses
        anything wider than 320 px outright.

  FLASH the file itself has to fit on the drive (and be downloaded, if it
        came from GIPHY). That is helped by fewer frames, fewer colours,
        and smaller dimensions.

Shrinking the picture is the only knob that helps both.
"""

import argparse
import os
import sys

try:
    from PIL import Image, ImageSequence
except ImportError:
    sys.exit("This needs Pillow:  pip install Pillow")

# The badge's panel, and gifio's hard limit.
SCREEN_W, SCREEN_H = 128, 160
GIFIO_MAX_W = 320


def ram_bytes(w, h):
    """What one decoded frame costs on the badge."""
    return w * h * 2


def load_frames(im):
    """Flatten a GIF to a list of (RGB image, duration_ms).

    GIF frames can be partial updates of the frame before them, so each
    one is composited onto the running canvas rather than used directly.
    Pillow's `convert("RGB")` per frame does this correctly as long as we
    let the iterator do the disposal handling.
    """
    frames = []
    for frame in ImageSequence.Iterator(im):
        duration = frame.info.get("duration", im.info.get("duration", 100))
        frames.append((frame.convert("RGB"), duration))
    return frames


def fit_size(w, h, max_w, max_h):
    """Scale to fit inside max_w x max_h, preserving aspect ratio."""
    scale = min(max_w / w, max_h / h, 1.0)
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def main():
    ap = argparse.ArgumentParser(
        description="Shrink a GIF so the badge can play it.")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="defaults to INPUT.badge.gif")
    ap.add_argument("--max-width", type=int, default=SCREEN_W,
                    help="default %d (the panel width)" % SCREEN_W)
    ap.add_argument("--max-height", type=int, default=SCREEN_H,
                    help="default %d (the panel height)" % SCREEN_H)
    ap.add_argument("--colors", type=int, default=128,
                    help="palette size, 2-256 (default 128)")
    ap.add_argument("--keep-every", type=int, default=1, metavar="N",
                    help="keep 1 frame in N, lengthening the rest to match")
    ap.add_argument("--max-frames", type=int, default=0,
                    help="hard cap on frames (0 = no cap)")
    args = ap.parse_args()

    out_path = args.output or (os.path.splitext(args.input)[0] + ".badge.gif")

    src = Image.open(args.input)
    in_w, in_h = src.size
    frames = load_frames(src)
    in_frames = len(frames)
    in_size = os.path.getsize(args.input)

    # --- frames -------------------------------------------------------
    if args.keep_every > 1:
        kept = []
        for i in range(0, len(frames), args.keep_every):
            # Absorb the dropped frames' time so the GIF still runs at
            # the speed it was drawn at, just choppier.
            span = frames[i:i + args.keep_every]
            total = sum(d for (_f, d) in span)
            kept.append((span[0][0], total))
        frames = kept
    if args.max_frames and len(frames) > args.max_frames:
        frames = frames[:args.max_frames]

    # --- size ---------------------------------------------------------
    out_w, out_h = fit_size(in_w, in_h, args.max_width, args.max_height)
    resized = [(f.resize((out_w, out_h), Image.LANCZOS), d) for (f, d) in frames]

    # --- colours ------------------------------------------------------
    # One shared palette from the first frame keeps inter-frame diffs
    # small; a per-frame palette would defeat `optimize=True`.
    colors = max(2, min(256, args.colors))
    base = resized[0][0].quantize(colors=colors, method=Image.MEDIANCUT)
    out_frames = [f.quantize(palette=base, dither=Image.FLOYDSTEINBERG)
                  for (f, _d) in resized]
    durations = [d for (_f, d) in resized]

    out_frames[0].save(out_path, save_all=True, append_images=out_frames[1:],
                       duration=durations, loop=0, optimize=True)

    out_size = os.path.getsize(out_path)
    in_ram = ram_bytes(in_w, in_h)
    out_ram = ram_bytes(out_w, out_h)

    print("%-22s %-18s -> %s" % ("", os.path.basename(args.input),
                                 os.path.basename(out_path)))
    print("%-22s %-18s    %s" % ("dimensions",
                                 "%dx%d" % (in_w, in_h),
                                 "%dx%d" % (out_w, out_h)))
    print("%-22s %-18s    %s" % ("frames", in_frames, len(out_frames)))
    print("%-22s %-18s    %s" % ("file size (flash)",
                                 "%.1f KB" % (in_size / 1024),
                                 "%.1f KB  (%.0f%% smaller)"
                                 % (out_size / 1024,
                                    100 * (1 - out_size / in_size))))
    print("%-22s %-18s    %s" % ("frame buffer (RAM)",
                                 "%.1f KB" % (in_ram / 1024),
                                 "%.1f KB  (%.0f%% smaller)"
                                 % (out_ram / 1024,
                                    100 * (1 - out_ram / in_ram))))

    print()
    if in_w > GIFIO_MAX_W:
        print("  the original was over gifio's %d px width limit -- it could"
              % GIFIO_MAX_W)
        print("  not have been opened at all")
    if out_ram > 60 * 1024:
        print("  WARNING: %.0f KB per frame is a lot for a board with no"
              % (out_ram / 1024))
        print("  PSRAM. Try --max-width 96 if it fails to open.")
    else:
        print("  %.0f KB per frame is comfortable." % (out_ram / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
