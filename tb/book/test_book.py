import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "model"))
import book  # noqa: E402

CLOCK_PERIOD_NS = 10
CAPACITY = 4  # matches -GCAPACITY=4 in the Makefile


def add(order_ref, side, shares, price):
    return {"type": "A", "order_ref": order_ref, "side": side, "shares": shares, "price": price}


def execute(order_ref, executed_shares):
    return {"type": "E", "order_ref": order_ref, "executed_shares": executed_shares}


def cancel(order_ref, cancelled_shares):
    return {"type": "X", "order_ref": order_ref, "cancelled_shares": cancelled_shares}


def delete(order_ref):
    return {"type": "D", "order_ref": order_ref}


def replace(original_order_ref, new_order_ref, shares, price):
    return {
        "type": "U", "original_order_ref": original_order_ref,
        "new_order_ref": new_order_ref, "shares": shares, "price": price,
    }


async def reset_dut(dut):
    cocotb.start_soon(Clock(dut.clk, CLOCK_PERIOD_NS, unit="ns").start())
    dut.rst.value = 1
    dut.msg_valid.value = 0
    dut.msg_type.value = 0
    dut.order_ref.value = 0
    dut.side.value = 0
    dut.shares.value = 0
    dut.price.value = 0
    dut.executed_shares.value = 0
    dut.cancelled_shares.value = 0
    dut.original_order_ref.value = 0
    dut.new_order_ref.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def apply_message(dut, msg):
    dut.msg_valid.value = 1
    dut.msg_type.value = ord(msg["type"])
    dut.order_ref.value = msg.get("order_ref", 0)
    dut.side.value = ord(msg["side"]) if "side" in msg else 0
    dut.shares.value = msg.get("shares", 0)
    dut.price.value = msg.get("price", 0)
    dut.executed_shares.value = msg.get("executed_shares", 0)
    dut.cancelled_shares.value = msg.get("cancelled_shares", 0)
    dut.original_order_ref.value = msg.get("original_order_ref", 0)
    dut.new_order_ref.value = msg.get("new_order_ref", 0)
    await RisingEdge(dut.clk)  # this edge latches the result for the message
    dut.msg_valid.value = 0
    # same simulator quirk noted in test_itch_decode.py: a value read right
    # after RisingEdge is one edge behind, so this edge is what lets us
    # correctly read the result the previous edge just latched
    await RisingEdge(dut.clk)


def check_top(dut, err, bid, ask):
    assert int(dut.update_valid.value) == (0 if err else 1), "update_valid mismatch"
    assert int(dut.err_valid.value) == (1 if err else 0), "err_valid mismatch"

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


async def apply_and_check(dut, model, msg):
    err, bid, ask = model.apply(msg)
    await apply_message(dut, msg)
    check_top(dut, err, bid, ask)


@cocotb.test()
async def test_single_buy_order(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "B", 100, 5000))


@cocotb.test()
async def test_single_sell_order(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "S", 100, 5000))


@cocotb.test()
async def test_best_bid_tracks_highest_price(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "B", 100, 5000))
    await apply_and_check(dut, model, add(2, "B", 50, 4900))
    await apply_and_check(dut, model, add(3, "B", 75, 5100))


@cocotb.test()
async def test_best_ask_tracks_lowest_price(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "S", 100, 5000))
    await apply_and_check(dut, model, add(2, "S", 50, 5100))
    await apply_and_check(dut, model, add(3, "S", 75, 4900))


@cocotb.test()
async def test_same_price_aggregates_quantity(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "B", 100, 5000))
    await apply_and_check(dut, model, add(2, "B", 50, 5000))


@cocotb.test()
async def test_partial_execution_reduces_quantity(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "B", 100, 5000))
    await apply_and_check(dut, model, execute(1, 30))


@cocotb.test()
async def test_full_execution_falls_back_to_next_best(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "B", 100, 5000))
    await apply_and_check(dut, model, add(2, "B", 50, 4900))
    await apply_and_check(dut, model, execute(1, 100))


@cocotb.test()
async def test_cancel_reduces_and_removes(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "S", 100, 5000))
    await apply_and_check(dut, model, cancel(1, 40))
    await apply_and_check(dut, model, cancel(1, 60))


@cocotb.test()
async def test_delete_removes_regardless_of_remaining_shares(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "B", 100, 5000))
    await apply_and_check(dut, model, delete(1))


@cocotb.test()
async def test_replace_changes_price_keeps_side(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "S", 100, 5000))
    await apply_and_check(dut, model, replace(1, 2, 80, 4800))


@cocotb.test()
async def test_unknown_order_ref_is_rejected(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    await apply_and_check(dut, model, add(1, "B", 100, 5000))
    await apply_and_check(dut, model, execute(999, 10))
    await apply_and_check(dut, model, cancel(999, 10))
    await apply_and_check(dut, model, delete(999))
    await apply_and_check(dut, model, replace(999, 1000, 10, 100))


@cocotb.test()
async def test_full_table_is_rejected(dut):
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    for i in range(CAPACITY):
        await apply_and_check(dut, model, add(i + 1, "B", 10, 5000 + i))
    await apply_and_check(dut, model, add(999, "B", 10, 6000))
