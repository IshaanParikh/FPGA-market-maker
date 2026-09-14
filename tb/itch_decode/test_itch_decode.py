import os
import struct
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "model"))
import itch  # noqa: E402

CLOCK_PERIOD_NS = 10

# ASCII fields: model strips padding for stock/attribution, keeps side/printable as-is
TEXT_FIELDS = {"side", "printable", "stock", "attribution"}
FIELD_BYTES = {
    "stock_locate": 2, "tracking_number": 2, "timestamp": 6,
    "order_ref": 8, "side": 1, "shares": 4, "stock": 8, "price": 4,
    "executed_shares": 4, "match_number": 8, "printable": 1,
    "cancelled_shares": 4, "original_order_ref": 8, "new_order_ref": 8,
    "attribution": 4,
}


async def reset_dut(dut):
    cocotb.start_soon(Clock(dut.clk, CLOCK_PERIOD_NS, unit="ns").start())
    dut.rst.value = 1
    dut.valid_in.value = 0
    dut.data_in.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def clock_byte(dut, byte):
    dut.data_in.value = byte
    dut.valid_in.value = 1
    await RisingEdge(dut.clk)


async def send_message(dut, payload):
    length = len(payload)
    frame = bytes([(length >> 8) & 0xFF, length & 0xFF]) + payload
    for b in frame:
        await clock_byte(dut, b)
    dut.valid_in.value = 0
    await RisingEdge(dut.clk)  # ST_DECODE: result registers one cycle after the last body byte
    # this simulator setup reads a signal's value from one edge behind if
    # sampled right after RisingEdge, so wait one more edge before reading
    await RisingEdge(dut.clk)


def field_value(dut, name):
    raw = int(getattr(dut, name).value)
    if name in TEXT_FIELDS:
        text = raw.to_bytes(FIELD_BYTES[name], "big").decode("ascii")
        return text if name in ("side", "printable") else text.rstrip()
    return raw


def check_decoded(dut, expected):
    assert int(dut.msg_valid.value) == 1, "msg_valid did not pulse"
    assert int(dut.err_valid.value) == 0, "err_valid should not pulse on a valid message"
    assert chr(int(dut.msg_type.value)) == expected["type"], "msg_type mismatch"
    for name, exp_value in expected.items():
        if name == "type":
            continue
        got = field_value(dut, name)
        assert got == exp_value, f"{name}: expected {exp_value!r}, got {got!r}"


@cocotb.test()
async def test_add_order(dut):
    await reset_dut(dut)
    payload = struct.pack(
        ">cHH6sQcI8sI",
        b"A", 7, 100, (12345).to_bytes(6, "big"),
        555, b"B", 200, b"AAPL    ", 1500000,
    )
    expected = itch.decode(payload)
    await send_message(dut, payload)
    check_decoded(dut, expected)


@cocotb.test()
async def test_add_order_mpid(dut):
    await reset_dut(dut)
    payload = struct.pack(
        ">cHH6sQcI8sI4s",
        b"F", 7, 100, (12345).to_bytes(6, "big"),
        556, b"S", 300, b"MSFT    ", 4200000, b"NSDQ",
    )
    expected = itch.decode(payload)
    await send_message(dut, payload)
    check_decoded(dut, expected)


@cocotb.test()
async def test_order_executed(dut):
    await reset_dut(dut)
    payload = struct.pack(
        ">cHH6sQIQ",
        b"E", 7, 101, (12400).to_bytes(6, "big"),
        555, 100, 999888,
    )
    expected = itch.decode(payload)
    await send_message(dut, payload)
    check_decoded(dut, expected)


@cocotb.test()
async def test_order_executed_with_price(dut):
    await reset_dut(dut)
    payload = struct.pack(
        ">cHH6sQIQcI",
        b"C", 7, 102, (12450).to_bytes(6, "big"),
        555, 50, 999889, b"Y", 1510000,
    )
    expected = itch.decode(payload)
    await send_message(dut, payload)
    check_decoded(dut, expected)


@cocotb.test()
async def test_order_cancel(dut):
    await reset_dut(dut)
    payload = struct.pack(
        ">cHH6sQI",
        b"X", 7, 103, (12500).to_bytes(6, "big"),
        555, 25,
    )
    expected = itch.decode(payload)
    await send_message(dut, payload)
    check_decoded(dut, expected)


@cocotb.test()
async def test_order_delete(dut):
    await reset_dut(dut)
    payload = struct.pack(
        ">cHH6sQ",
        b"D", 7, 104, (12550).to_bytes(6, "big"),
        555,
    )
    expected = itch.decode(payload)
    await send_message(dut, payload)
    check_decoded(dut, expected)


@cocotb.test()
async def test_order_replace(dut):
    await reset_dut(dut)
    payload = struct.pack(
        ">cHH6sQQII",
        b"U", 7, 105, (12600).to_bytes(6, "big"),
        555, 777, 150, 1495000,
    )
    expected = itch.decode(payload)
    await send_message(dut, payload)
    check_decoded(dut, expected)


@cocotb.test()
async def test_unsupported_type_rejected(dut):
    await reset_dut(dut)
    payload = b"S" + bytes(11)
    await send_message(dut, payload)
    assert int(dut.msg_valid.value) == 0, "msg_valid should not pulse for an unsupported type"
    assert int(dut.err_valid.value) == 1, "err_valid did not pulse for an unsupported type"


@cocotb.test()
async def test_wrong_length_rejected(dut):
    await reset_dut(dut)
    # a well formed delete body, framed with one extra byte of declared length
    payload = struct.pack(">cHH6sQ", b"D", 7, 104, (12550).to_bytes(6, "big"), 555)
    length = len(payload) + 1
    frame = bytes([(length >> 8) & 0xFF, length & 0xFF]) + payload
    for b in frame:
        await clock_byte(dut, b)
    await clock_byte(dut, 0)  # the extra byte framing said was coming
    dut.valid_in.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)  # see the comment in send_message
    assert int(dut.msg_valid.value) == 0, "msg_valid should not pulse when length does not match the type"
    assert int(dut.err_valid.value) == 1, "err_valid did not pulse for a length mismatch"


@cocotb.test()
async def test_back_to_back_messages(dut):
    await reset_dut(dut)
    delete_payload = struct.pack(">cHH6sQ", b"D", 7, 104, (12550).to_bytes(6, "big"), 555)
    cancel_payload = struct.pack(">cHH6sQI", b"X", 7, 103, (12500).to_bytes(6, "big"), 555, 25)

    await send_message(dut, delete_payload)
    check_decoded(dut, itch.decode(delete_payload))

    await send_message(dut, cancel_payload)
    check_decoded(dut, itch.decode(cancel_payload))


@cocotb.test()
async def test_zero_length_frame_rejected(dut):
    # a declared length of 0 skips straight to decode with no body bytes;
    # no real message type is ever 0 bytes long, so this must always error
    await reset_dut(dut)
    await clock_byte(dut, 0)
    await clock_byte(dut, 0)
    dut.valid_in.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)  # see the comment in send_message
    assert int(dut.msg_valid.value) == 0, "msg_valid should not pulse for a zero length frame"
    assert int(dut.err_valid.value) == 1, "err_valid did not pulse for a zero length frame"


@cocotb.test()
async def test_pause_mid_message_resumes_correctly(dut):
    # every state only advances when valid_in is high, so dropping valid_in
    # partway through a message should just hold everything in place
    await reset_dut(dut)
    payload = struct.pack(">cHH6sQ", b"D", 7, 104, (12550).to_bytes(6, "big"), 555)
    length = len(payload)
    frame = bytes([(length >> 8) & 0xFF, length & 0xFF]) + payload

    half = len(frame) // 2
    for b in frame[:half]:
        await clock_byte(dut, b)

    dut.valid_in.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk)

    for b in frame[half:]:
        await clock_byte(dut, b)
    dut.valid_in.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    check_decoded(dut, itch.decode(payload))


@cocotb.test()
async def test_no_gap_between_messages(dut):
    # ST_DECODE does not look at data_in at all (see the comment above that
    # state), so whatever byte arrives on that one cycle is never captured
    # as anything. This sends two messages with no gap between them, then
    # checks whether a cleanly framed message right after still decodes.
    await reset_dut(dut)

    def framed(payload):
        length = len(payload)
        return bytes([(length >> 8) & 0xFF, length & 0xFF]) + payload

    delete_payload = struct.pack(">cHH6sQ", b"D", 7, 104, (12550).to_bytes(6, "big"), 555)
    cancel_payload = struct.pack(">cHH6sQI", b"X", 7, 103, (12500).to_bytes(6, "big"), 555, 25)

    for b in framed(delete_payload) + framed(cancel_payload):
        await clock_byte(dut, b)

    dut.valid_in.value = 0
    for _ in range(20):
        await RisingEdge(dut.clk)

    add_payload = struct.pack(
        ">cHH6sQcI8sI",
        b"A", 7, 100, (12345).to_bytes(6, "big"),
        900, b"B", 200, b"AAPL    ", 1500000,
    )
    await send_message(dut, add_payload)
    assert int(dut.msg_valid.value) == 0, (
        "a byte is dropped on the cycle after the last body byte, so back "
        "to back messages with no gap should desync framing: a cleanly "
        "framed message sent afterward should not decode either"
    )
