import os
import random
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "model"))
import board_link as bl  # noqa: E402

CAPACITY = 8  # matches -GCAPACITY=8 in the Makefile


async def reset_dut(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.clear.value = 0
    dut.rx_valid.value = 0
    dut.rx_byte.value = 0
    dut.tx_ready.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def send_bytes(dut, data, gap=0):
    """One byte per rx_valid pulse, with `gap` idle cycles between bytes
    (the EPT link delivers bytes thousands of cycles apart)."""
    for b in data:
        dut.rx_byte.value = b
        dut.rx_valid.value = 1
        await RisingEdge(dut.clk)
        dut.rx_valid.value = 0
        if gap:
            await ClockCycles(dut.clk, gap)


async def read_reply(dut, ready_prob=1.0, rng=None, timeout=500):
    """Collect one 17 byte reply, applying back-pressure on tx_ready."""
    got = bytearray()
    cycles = 0
    while len(got) < bl.REPLY_BYTES:
        ready = 1 if rng is None or rng.random() < ready_prob else 0
        dut.tx_ready.value = ready
        await RisingEdge(dut.clk)
        if ready and int(dut.tx_valid.value):
            got.append(int(dut.tx_byte.value))
        cycles += 1
        assert cycles < timeout, "no reply from the bridge"
    dut.tx_ready.value = 0
    await RisingEdge(dut.clk)
    assert int(dut.tx_valid.value) == 0, "bridge sent more than 17 bytes"
    return bytes(got)


async def round_trip(dut, model, payload, gap=0, ready_prob=1.0, rng=None):
    await send_bytes(dut, bl.framed(payload), gap)
    got = await read_reply(dut, ready_prob, rng)
    exp = model.reply(payload)
    assert got == exp, "reply mismatch for %r\n  got %s\n  exp %s" % (
        payload[:1], bl.describe_reply(got), bl.describe_reply(exp))


@cocotb.test()
async def test_basic_session(dut):
    """Every message type plus decode and book errors, one frame at a time."""
    await reset_dut(dut)
    model = bl.BoardModel(CAPACITY)
    for payload in bl.basic_session():
        await round_trip(dut, model, payload)
    assert int(dut.overrun.value) == 0


@cocotb.test()
async def test_no_reply_until_frame_complete(dut):
    """The reply must not start before the last byte is in, however slowly
    the bytes arrive: the EPT link corrupts bytes if the directions overlap."""
    await reset_dut(dut)
    frame = bl.framed(bl.encode_add(1, "B", 10, 5000))
    dut.tx_ready.value = 1
    for b in frame[:-1]:
        dut.rx_byte.value = b
        dut.rx_valid.value = 1
        await RisingEdge(dut.clk)
        dut.rx_valid.value = 0
        for _ in range(30):
            await RisingEdge(dut.clk)
            assert int(dut.tx_valid.value) == 0, "reply started before the frame was complete"
    dut.tx_ready.value = 0
    await send_bytes(dut, frame[-1:])
    got = await read_reply(dut)
    assert got == bl.BoardModel(CAPACITY).reply(bl.encode_add(1, "B", 10, 5000))


@cocotb.test()
async def test_random_with_gaps_and_backpressure(dut):
    """A long random session with idle gaps between bytes and a host that
    is slow to take reply bytes; the table fills and empties repeatedly."""
    await reset_dut(dut)
    rng = random.Random(7)
    model = bl.BoardModel(CAPACITY)
    for payload in bl.random_session(300, CAPACITY, seed=11):
        await round_trip(dut, model, payload, gap=rng.choice((0, 0, 1, 5)),
                         ready_prob=0.4, rng=rng)
    assert int(dut.overrun.value) == 0


@cocotb.test()
async def test_overrun_flagged_and_byte_dropped(dut):
    """A byte sent while a reply is pending is dropped and flagged, and the
    framing is not disturbed by it."""
    await reset_dut(dut)
    model = bl.BoardModel(CAPACITY)
    first = bl.encode_add(1, "B", 10, 5000)
    await send_bytes(dut, bl.framed(first))
    await ClockCycles(dut.clk, 20)       # reply now waiting on tx_ready
    await send_bytes(dut, b"\x55")       # host misbehaves
    await RisingEdge(dut.clk)            # let the flag register
    assert int(dut.overrun.value) == 1
    # this reply was captured before the stray byte, so it is clean
    assert await read_reply(dut) == model.reply(first)
    # framing is intact, and every later reply carries the sticky flag
    second = bl.encode_add(2, "S", 20, 5100)
    await send_bytes(dut, bl.framed(second))
    assert await read_reply(dut) == model.reply(second, overrun=True)


@cocotb.test()
async def test_clear_resets_book_and_framing(dut):
    """clear in the middle of a frame drops the partial frame, empties the
    book and clears the sticky flags."""
    await reset_dut(dut)
    model = bl.BoardModel(CAPACITY)
    await round_trip(dut, model, bl.encode_add(1, "B", 10, 5000))
    await send_bytes(dut, bl.framed(bl.encode_add(2, "B", 10, 5001))[:7])
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.clear.value = 0
    await RisingEdge(dut.clk)
    model = bl.BoardModel(CAPACITY)
    await round_trip(dut, model, bl.encode_add(3, "S", 30, 5200))
    assert int(dut.any_err.value) == 0
