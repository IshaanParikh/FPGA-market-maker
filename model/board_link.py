"""Host side of the board link in rtl/board/mm_bridge.sv: ITCH message
encoders, length framing, and the 17 byte reply the board sends back after
each frame, predicted from itch.py and book.py.

Shared by the bridge testbench (tb/board), the DueProLogic simulation
(syn/quartus/sim) and the hardware check (scripts/dpl_host.py), so all
three check the board against the same expectation.
"""

import random
import struct

import book
import itch

REPLY_BYTES = 17
STATUS_MARKER = 0b10 << 6

ST_DECODE_ERR = 1 << 0
ST_BOOK_ERR = 1 << 1
ST_BOOK_UPDATE = 1 << 2
ST_BID_VALID = 1 << 3
ST_ASK_VALID = 1 << 4
ST_OVERRUN = 1 << 5


def framed(payload):
    length = len(payload)
    return bytes([(length >> 8) & 0xFF, length & 0xFF]) + payload


def _ts(ts):
    return ts.to_bytes(6, "big")


def encode_add(order_ref, side, shares, price, mpid=None,
               stock=b"AAPL    ", stock_locate=7, tracking=100, ts=12345):
    if mpid is None:
        return struct.pack(">cHH6sQcI8sI", b"A", stock_locate, tracking, _ts(ts),
                           order_ref, side.encode(), shares, stock, price)
    return struct.pack(">cHH6sQcI8sI4s", b"F", stock_locate, tracking, _ts(ts),
                       order_ref, side.encode(), shares, stock, price, mpid)


def encode_execute(order_ref, executed_shares, match_number=1,
                   stock_locate=7, tracking=100, ts=12345):
    return struct.pack(">cHH6sQIQ", b"E", stock_locate, tracking, _ts(ts),
                       order_ref, executed_shares, match_number)


def encode_cancel(order_ref, cancelled_shares, stock_locate=7, tracking=100, ts=12345):
    return struct.pack(">cHH6sQI", b"X", stock_locate, tracking, _ts(ts),
                       order_ref, cancelled_shares)


def encode_delete(order_ref, stock_locate=7, tracking=100, ts=12345):
    return struct.pack(">cHH6sQ", b"D", stock_locate, tracking, _ts(ts), order_ref)


def encode_replace(original_order_ref, new_order_ref, shares, price,
                   stock_locate=7, tracking=100, ts=12345):
    return struct.pack(">cHH6sQQII", b"U", stock_locate, tracking, _ts(ts),
                       original_order_ref, new_order_ref, shares, price)


class BoardModel:
    """What the board should answer for each frame. Mirrors the hardware's
    book state, including the last best bid/ask, which the hardware holds
    across a frame that fails to decode."""

    def __init__(self, capacity):
        self.book = book.OrderBook(capacity=capacity)
        self.bid = (None, 0)
        self.ask = (None, 0)

    def reply(self, payload, overrun=False):
        status = STATUS_MARKER
        if overrun:
            status |= ST_OVERRUN
        try:
            msg = itch.decode(payload)
        except itch.DecodeError:
            status |= ST_DECODE_ERR
        else:
            err, self.bid, self.ask = self.book.apply(msg)
            status |= ST_BOOK_ERR if err else ST_BOOK_UPDATE
        bid_price, bid_qty = self.bid
        ask_price, ask_qty = self.ask
        if bid_price is not None:
            status |= ST_BID_VALID
        if ask_price is not None:
            status |= ST_ASK_VALID
        return bytes([status]) + struct.pack(
            ">IIII",
            bid_price or 0, bid_qty if bid_price is not None else 0,
            ask_price or 0, ask_qty if ask_price is not None else 0,
        )


def describe_reply(reply):
    status = reply[0]
    bid_price, bid_qty, ask_price, ask_qty = struct.unpack(">IIII", reply[1:17])
    flags = [name for bit, name in (
        (ST_DECODE_ERR, "decode_err"), (ST_BOOK_ERR, "book_err"),
        (ST_BOOK_UPDATE, "update"), (ST_OVERRUN, "overrun"),
    ) if status & bit]
    bid = "%d x %d" % (bid_price, bid_qty) if status & ST_BID_VALID else "-"
    ask = "%d x %d" % (ask_price, ask_qty) if status & ST_ASK_VALID else "-"
    return "status=%02x [%s] bid %s  ask %s" % (status, ",".join(flags) or "none", bid, ask)


def basic_session():
    """Every message type, an undecodable frame, a zero length frame and a
    book error, in a fixed order."""
    return [
        encode_add(1, "B", 100, 5000),
        encode_add(2, "S", 80, 5100),
        encode_add(3, "B", 50, 4900),
        encode_execute(1, 40),
        encode_cancel(2, 30),
        encode_replace(3, 4, 60, 4950),
        encode_add(5, "S", 90, 5050, mpid=b"NSDQ"),
        b"S" + bytes(11),        # unsupported type: decode error
        b"",                     # zero length frame: decode error
        encode_delete(999),      # no such order: book error
        encode_delete(4),
        encode_add(6, "B", 70, 5000),
    ]


def random_session(n, capacity, seed=1):
    """A random but valid-heavy stream that keeps the book near full, with
    the occasional bad frame."""
    rng = random.Random(seed)
    live = []
    next_ref = 100
    msgs = []
    for _ in range(n):
        r = rng.random()
        if r < 0.05:
            msgs.append(bytes([ord("Z")]) + bytes(rng.randrange(0, 40)))
        elif not live or (r < 0.45 and len(live) <= capacity):
            side = rng.choice("BS")
            price = rng.randrange(4990, 5010) if side == "B" else rng.randrange(5005, 5025)
            msgs.append(encode_add(next_ref, side, rng.randrange(1, 500), price,
                                   mpid=b"MPID" if rng.random() < 0.2 else None))
            live.append(next_ref)
            next_ref += 1
        else:
            ref = rng.choice(live)
            kind = rng.random()
            if kind < 0.25:
                msgs.append(encode_execute(ref, rng.randrange(1, 300)))
            elif kind < 0.5:
                msgs.append(encode_cancel(ref, rng.randrange(1, 300)))
            elif kind < 0.75:
                msgs.append(encode_delete(ref))
                live.remove(ref)
            else:
                msgs.append(encode_replace(ref, next_ref, rng.randrange(1, 500),
                                           rng.randrange(4990, 5025)))
                live[live.index(ref)] = next_ref
                next_ref += 1
    return msgs
