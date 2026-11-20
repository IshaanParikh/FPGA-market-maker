#!/usr/bin/env python3
"""
Drive the market maker running on the EPT DueProLogic and check every reply
against the Python models (model/itch.py + model/book.py).

Talks EPT's Active Transfer framing straight over the FT2232H UART, so no
Active Host DLL is needed. Each transfer is {2'b10|2'b11, cmd[2:0],
addr[2:0]} followed by one payload byte; syn/quartus/dpl_top.sv and
rtl/board/mm_bridge.sv have the details.

Lockstep, one ITCH frame in flight: send a frame, read its 17 byte reply,
then send the next. EPT's library garbles a byte if the two directions
overlap. Each round trip waits on the FTDI latency timer, so set it to 1 ms
(Device Manager > the COM port > Port Settings > Advanced).

Use whichever FT2232H COM port is the UART; the other one belongs to
EPT-Blaster.

    pip install pyserial
    python scripts/dpl_host.py --port COM14                  # basic session
    python scripts/dpl_host.py --port COM14 --random 2000    # plus a random one
    python scripts/dpl_host.py --port COM14 --verbose        # print every reply

Run from the repo root. --capacity must match the CAPACITY the board was
built with (default 8).
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import board_link as bl  # noqa: E402

CMD_TRIGGER = 0x1
CMD_TRANSFER = 0x2


def frame(cmd, addr, payload, to_host=False):
    hdr = (0xC0 if to_host else 0x80) | (cmd << 3) | addr
    return bytes([hdr, payload & 0xFF])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hardware check of the market maker on the DueProLogic.")
    ap.add_argument("--port", required=True, help="FT2232H UART port, e.g. COM14")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--addr", type=int, default=1, help="MM_ADDR in dpl_top.sv")
    ap.add_argument("--capacity", type=int, default=8, help="CAPACITY the board was built with")
    ap.add_argument("--random", type=int, default=0, help="random frames to send after the basic session")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    import serial  # pyserial, only needed here

    payloads = bl.basic_session()
    if args.random:
        payloads += bl.random_session(args.random, args.capacity, seed=args.seed)

    model = bl.BoardModel(args.capacity)
    reply_hdr = frame(CMD_TRANSFER, args.addr, 0, to_host=True)[0]
    mismatches = 0

    with serial.Serial(args.port, args.baud, timeout=args.timeout) as port:
        port.reset_input_buffer()
        # trigger bit 0: empty the book and resync framing
        port.write(frame(CMD_TRIGGER, 0, 0x01))
        port.flush()
        time.sleep(0.05)
        port.reset_input_buffer()

        t0 = time.time()
        for n, payload in enumerate(payloads):
            port.write(b"".join(frame(CMD_TRANSFER, args.addr, b) for b in bl.framed(payload)))
            raw = port.read(2 * bl.REPLY_BYTES)
            if len(raw) < 2 * bl.REPLY_BYTES:
                print("timed out on frame %d (%d of %d reply bytes)" % (n, len(raw) // 2, bl.REPLY_BYTES))
                return 1
            if any(h != reply_hdr for h in raw[0::2]):
                print("bad transfer header on frame %d: %s" % (n, raw.hex()))
                return 1
            got = bytes(raw[1::2])
            exp = model.reply(payload)
            if args.verbose:
                print("[%4d] %-6r %s" % (n, payload[:1], bl.describe_reply(got)))
            if got != exp:
                mismatches += 1
                if mismatches <= 10:
                    print("frame %d (%r) mismatch\n  got %s\n  exp %s" % (
                        n, payload[:1], bl.describe_reply(got), bl.describe_reply(exp)))
        dt = time.time() - t0

    print("frames      : %d in %.1f s (%.0f frames/s)" % (len(payloads), dt, len(payloads) / dt))
    print("mismatches  : %d" % mismatches)
    print("PASS" if mismatches == 0 else "FAIL")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
