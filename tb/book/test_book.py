import os
import random
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


@cocotb.test()
async def test_freed_slot_is_reused(dut):
    # fills the table, frees one entry (not the first one, so this actually
    # exercises finding a slot in the middle), then confirms a new order
    # can take that freed slot instead of being wrongly rejected as full
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    for i in range(CAPACITY):
        await apply_and_check(dut, model, add(i + 1, "B", 10, 5000 + i))
    await apply_and_check(dut, model, delete(2))
    await apply_and_check(dut, model, add(999, "B", 10, 6000))


def random_message(rng, model, next_ref):
    """One random message plus the next unused order ref to hand out.
    Mostly targets orders the model currently considers live, but
    occasionally aims at a made up ref to exercise the error path too."""
    live = list(model.orders.keys())
    kind = rng.choice(["add", "add", "exec", "cancel", "delete", "replace"])

    if kind == "add" or not live:
        msg = add(next_ref, rng.choice("BS"), rng.randint(1, 500), rng.randint(1, 100_000))
        return msg, next_ref + 1

    ref = rng.choice(live) if rng.random() < 0.85 else rng.randint(1, 1_000_000)
    if kind == "exec":
        return execute(ref, rng.randint(1, 600)), next_ref
    if kind == "cancel":
        return cancel(ref, rng.randint(1, 600)), next_ref
    if kind == "delete":
        return delete(ref), next_ref
    return replace(ref, next_ref, rng.randint(1, 500), rng.randint(1, 100_000)), next_ref + 1


@cocotb.test()
async def test_random_sequence_matches_model(dut):
    # throws a long pseudo random mix of adds, executions, cancels,
    # deletes, and replaces at the DUT and the model side by side, and
    # checks they agree after every one. A handful of hand picked
    # scenarios only proves the cases someone thought to write; this
    # covers interactions between operations that those miss.
    await reset_dut(dut)
    model = book.OrderBook(capacity=CAPACITY)
    rng = random.Random(20260914)
    next_ref = 1
    for _ in range(500):
        msg, next_ref = random_message(rng, model, next_ref)
        await apply_and_check(dut, model, msg)
