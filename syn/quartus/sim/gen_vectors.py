#!/usr/bin/env python3
"""Writes the stimulus and expected replies for tb_dpl_top.sv: every ITCH
frame the testbench sends, and the 17 byte reply the board model predicts
for each. Run by run_dpl_sim.sh.

    frames.hex   all frame bytes back to back (length prefix included)
    lens.hex     the length of each frame on the wire, one per line
    replies.hex  17 expected reply bytes per frame
    vectors.vh   counts, for the testbench
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "model"))
import board_link as bl  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--capacity", type=int, default=8)
    ap.add_argument("--random", type=int, default=24, help="random frames after the basic session")
    args = ap.parse_args()

    model = bl.BoardModel(args.capacity)
    payloads = bl.basic_session() + bl.random_session(args.random, args.capacity, seed=3)
    frames = [bl.framed(p) for p in payloads]
    replies = [model.reply(p) for p in payloads]

    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "frames.hex"), "w") as f:
        for fr in frames:
            f.write("".join("%02x\n" % b for b in fr))
    with open(os.path.join(args.outdir, "lens.hex"), "w") as f:
        f.write("".join("%04x\n" % len(fr) for fr in frames))
    with open(os.path.join(args.outdir, "replies.hex"), "w") as f:
        for r in replies:
            f.write("".join("%02x\n" % b for b in r))
    with open(os.path.join(args.outdir, "vectors.vh"), "w") as f:
        f.write("`define N_FRAMES %d\n" % len(frames))
        f.write("`define N_FRAME_BYTES %d\n" % sum(len(fr) for fr in frames))
        f.write("`define CAPACITY %d\n" % args.capacity)
    print("%d frames, %d bytes" % (len(frames), sum(len(fr) for fr in frames)))


if __name__ == "__main__":
    main()
