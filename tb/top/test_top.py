import os
import struct
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "model"))
import book  # noqa: E402
import itch  # noqa: E402

CLOCK_PERIOD_NS = 10
CAPACITY = 4  # matches -GCAPACITY=4 in the Makefile


def framed(payload):
    length = len(payload)
    return bytes([(length >> 8) & 0xFF, length & 0xFF]) + payload


def encode_add(order_ref, side, shares, price, mpid=None,
               stock=b"AAPL    ", stock_locate=7, tracking=100, ts=12345):
    ts_bytes = ts.to_bytes(6, "big")
    if mpid is None:
        return struct.pack(
            ">cHH6sQcI8sI",
            b"A", stock_locate, tracking, ts_bytes,
            order_ref, side.encode(), shares, stock, price,
        )
    return struct.pack(
        ">cHH6sQcI8sI4s",
        b"F", stock_locate, tracking, ts_bytes,
        order_ref, side.encode(), shares, stock, price, mpid,
    )


def encode_execute(order_ref, executed_shares, match_number=1, stock_locate=7, tracking=100, ts=12345):
    return struct.pack(
        ">cHH6sQIQ",
        b"E", stock_locate, tracking, ts.to_bytes(6, "big"),
        order_ref, executed_shares, match_number,
    )


def encode_cancel(order_ref, cancelled_shares, stock_locate=7, tracking=100, ts=12345):
    return struct.pack(
        ">cHH6sQI",
        b"X", stock_locate, tracking, ts.to_bytes(6, "big"),
        order_ref, cancelled_shares,
    )


def encode_delete(order_ref, stock_locate=7, tracking=100, ts=12345):
    return struct.pack(
        ">cHH6sQ",
        b"D", stock_locate, tracking, ts.to_bytes(6, "big"), order_ref,
    )


def encode_replace(original_order_ref, new_order_ref, shares, price, stock_locate=7, tracking=100, ts=12345):
    return struct.pack(
        ">cHH6sQQII",
        b"U", stock_locate, tracking, ts.to_bytes(6, "big"),
        original_order_ref, new_order_ref, shares, price,
    )


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
    """Streams one framed payload in and waits for itch_decode's own
    outputs to settle (2 edges, same as test_itch_decode.py). Does not
    wait for order_book: a decode error never reaches it, so the caller
    checks decode_err before deciding whether to wait further."""
    for b in framed(payload):
        await clock_byte(dut, b)
    dut.valid_in.value = 0
    await RisingEdge(dut.clk)  # itch_decode: msg_valid/err_valid register here
    await RisingEdge(dut.clk)  # simulator quirk, see test_itch_decode.py's send_message


async def settle_book(dut):
    # order_book takes msg_valid straight from itch_decode's output and
    # registers its own results one cycle later, so its outputs need one
    # more edge past send_message's before they can be read correctly
    await RisingEdge(dut.clk)


def check_book(dut, book_err, bid, ask):
    assert int(dut.book_update.value) == (0 if book_err else 1), "book_update mismatch"
    assert int(dut.book_err.value) == (1 if book_err else 0), "book_err mismatch"

    bid_price, bid_qty = bid
    if bid_price is None:
        assert int(dut.bid_valid.value) == 0, "bid_valid should be low with no resting buy orders"
    else:
        assert int(dut.bid_valid.value) == 1, "bid_valid should be high"
        assert int(dut.bid_price.value) == bid_price, "bid_price mismatch"
        assert int(dut.bid_qty.value) == bid_qty, "bid_qty mismatch"

    ask_price, ask_qty = ask
    if ask_price is None:
        assert int(dut.ask_valid.value) == 0, "ask_valid should be low with no resting sell orders"
    else:
        assert int(dut.ask_valid.value) == 1, "ask_valid should be high"
        assert int(dut.ask_price.value) == ask_price, "ask_price mismatch"
        assert int(dut.ask_qty.value) == ask_qty, "ask_qty mismatch"


async def send_and_check(dut, model, payload):
    """Sends one raw ITCH payload through the whole chip and checks it
    against itch.decode() and book.apply() run in Python. decode_err
    settles one edge before order_book's own outputs do, since it comes
    straight from itch_decode's register while the book's outputs pass
    through an extra one, so the two are read at different points."""
    try:
        msg = itch.decode(payload)
    except itch.DecodeError:
        await send_message(dut, payload)
        assert int(dut.decode_err.value) == 1, "decode_err did not pulse for an undecodable message"
        assert int(dut.book_update.value) == 0, "a decode error should never reach the book"
        assert int(dut.book_err.value) == 0, "a decode error should never reach the book"
        return

    err, bid, ask = model.apply(msg)
    await send_message(dut, payload)
    assert int(dut.decode_err.value) == 0, "decode_err should not pulse for a message that decodes fine"
    await settle_book(dut)
    check_book(dut, err, bid, ask)


@cocotb.test()
async def test_pipeline_matches_combined_model(dut):
    # a run touching every message type, streamed as raw bytes through
    # decode into the book, checked against the two Python models
    # composed the same way the chip is: decode, then apply
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)

    messages = [
        encode_add(1, "B", 100, 5000),
        encode_add(2, "S", 80, 5100),
        encode_add(3, "B", 50, 4900),
        encode_execute(1, 40),
        encode_cancel(2, 30),
        encode_replace(3, 4, 60, 4950),
        encode_add(5, "S", 90, 5050, mpid=b"NSDQ"),
        encode_delete(4),
    ]
    for payload in messages:
        await send_and_check(dut, model, payload)


@cocotb.test()
async def test_decode_error_does_not_reach_book(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await send_and_check(dut, model, encode_add(1, "B", 100, 5000))

    bad_payload = b"S" + bytes(11)  # unsupported message type
    await send_and_check(dut, model, bad_payload)

    # the book should be exactly as it was before the malformed message
    await send_and_check(dut, model, encode_delete(1))


@cocotb.test()
async def test_book_error_surfaces_separately_from_decode_error(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await send_and_check(dut, model, encode_delete(999))  # decodes fine, no such order


@cocotb.test()
async def test_table_full_surfaces_as_book_error(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    for i in range(CAPACITY):
        await send_and_check(dut, model, encode_add(i + 1, "B", 10, 5000 + i))
    await send_and_check(dut, model, encode_add(999, "B", 10, 6000))
