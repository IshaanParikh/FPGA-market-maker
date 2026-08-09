# ITCH 5.0 decoder, order book message types only:
# Add Order (A/F), Order Executed (E/C), Order Cancel (X), Order Delete (D),
# Order Replace (U). Any other message type is rejected, not skipped.
#
# Every message is big-endian and starts with type, stock locate, tracking
# number, and a 6 byte timestamp. struct has no 6 byte int, so the timestamp
# is unpacked as raw bytes and converted by hand.
#
# Price fields keep their raw integer value (4 implied decimal digits, per
# spec) instead of being converted to float, so they match what the RTL
# will carry.

import struct

_HEADER = "cHH6s"

_SPECS = {
    b"A": (
        ">" + _HEADER + "QcI8sI",
        ("type", "stock_locate", "tracking_number", "timestamp",
         "order_ref", "side", "shares", "stock", "price"),
    ),
    b"F": (
        ">" + _HEADER + "QcI8sI4s",
        ("type", "stock_locate", "tracking_number", "timestamp",
         "order_ref", "side", "shares", "stock", "price", "attribution"),
    ),
    b"E": (
        ">" + _HEADER + "QIQ",
        ("type", "stock_locate", "tracking_number", "timestamp",
         "order_ref", "executed_shares", "match_number"),
    ),
    b"C": (
        ">" + _HEADER + "QIQcI",
        ("type", "stock_locate", "tracking_number", "timestamp",
         "order_ref", "executed_shares", "match_number", "printable",
         "price"),
    ),
    b"X": (
        ">" + _HEADER + "QI",
        ("type", "stock_locate", "tracking_number", "timestamp",
         "order_ref", "cancelled_shares"),
    ),
    b"D": (
        ">" + _HEADER + "Q",
        ("type", "stock_locate", "tracking_number", "timestamp",
         "order_ref"),
    ),
    b"U": (
        ">" + _HEADER + "QQII",
        ("type", "stock_locate", "tracking_number", "timestamp",
         "original_order_ref", "new_order_ref", "shares", "price"),
    ),
}

_TEXT_FIELDS = ("side", "printable", "stock", "attribution")


class DecodeError(ValueError):
    pass


def message_length(msg_type):
    spec = _SPECS.get(msg_type)
    if spec is None:
        raise DecodeError(f"unsupported message type {msg_type!r}")
    return struct.calcsize(spec[0])


def decode(payload):
    if not payload:
        raise DecodeError("empty payload")
    msg_type = payload[0:1]
    spec = _SPECS.get(msg_type)
    if spec is None:
        raise DecodeError(f"unsupported message type {msg_type!r}")
    fmt, fields = spec
    size = struct.calcsize(fmt)
    if len(payload) != size:
        raise DecodeError(
            f"{msg_type!r} expects {size} bytes, got {len(payload)}"
        )
    msg = dict(zip(fields, struct.unpack(fmt, payload)))
    msg["type"] = msg_type.decode("ascii")
    msg["timestamp"] = int.from_bytes(msg["timestamp"], "big")
    for field in _TEXT_FIELDS:
        if field in msg:
            msg[field] = msg[field].decode("ascii").rstrip()
    return msg


def iter_messages(stream):
    offset = 0
    end = len(stream)
    while offset < end:
        if offset + 2 > end:
            raise DecodeError("truncated length prefix")
        length = int.from_bytes(stream[offset:offset + 2], "big")
        offset += 2
        if offset + length > end:
            raise DecodeError("truncated message body")
        yield decode(stream[offset:offset + length])
        offset += length
