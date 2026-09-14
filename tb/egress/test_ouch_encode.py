import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "model"))
import ouch  # noqa: E402

CLOCK_PERIOD_NS = 10


async def reset_dut(dut):
    cocotb.start_soon(Clock(dut.clk, CLOCK_PERIOD_NS, unit="ns").start())
    dut.rst.value = 1
    dut.req_valid.value = 0
    dut.msg_type.value = 0
    dut.user_ref_num.value = 0
    dut.orig_user_ref_num.value = 0
    dut.side.value = 0
    dut.quantity.value = 0
    dut.symbol.value = 0
    dut.price.value = 0
    dut.time_in_force.value = 0
    dut.display.value = 0
    dut.capacity.value = 0
    dut.iso_eligible.value = 0
    dut.cross_type.value = 0
    dut.clordid.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def drive_enter_order(dut, user_ref_num, side, quantity, symbol, price,
                             time_in_force="0", display="Y", capacity="A",
                             iso_eligible="N", cross_type="N", clordid=""):
    dut.req_valid.value = 1
    dut.msg_type.value = ord("O")
    dut.user_ref_num.value = user_ref_num
    dut.side.value = ord(side)
    dut.quantity.value = quantity
    dut.symbol.value = int.from_bytes(symbol.encode().ljust(8), "big")
    dut.price.value = price
    dut.time_in_force.value = ord(time_in_force)
    dut.display.value = ord(display)
    dut.capacity.value = ord(capacity)
    dut.iso_eligible.value = ord(iso_eligible)
    dut.cross_type.value = ord(cross_type)
    dut.clordid.value = int.from_bytes(clordid.encode().ljust(14), "big")
    await RisingEdge(dut.clk)  # ST_IDLE consumes the request here
    dut.req_valid.value = 0


async def drive_replace_order(dut, orig_user_ref_num, user_ref_num, quantity, price,
                               time_in_force="0", display="Y", iso_eligible="N", clordid=""):
    dut.req_valid.value = 1
    dut.msg_type.value = ord("U")
    dut.orig_user_ref_num.value = orig_user_ref_num
    dut.user_ref_num.value = user_ref_num
    dut.quantity.value = quantity
    dut.price.value = price
    dut.time_in_force.value = ord(time_in_force)
    dut.display.value = ord(display)
    dut.iso_eligible.value = ord(iso_eligible)
    dut.clordid.value = int.from_bytes(clordid.encode().ljust(14), "big")
    await RisingEdge(dut.clk)
    dut.req_valid.value = 0


async def drive_cancel_order(dut, user_ref_num, quantity):
    dut.req_valid.value = 1
    dut.msg_type.value = ord("X")
    dut.user_ref_num.value = user_ref_num
    dut.quantity.value = quantity
    await RisingEdge(dut.clk)
    dut.req_valid.value = 0


async def collect_output(dut, expected_length, max_cycles=80):
    """Samples data_valid/data_out on the falling edge of every cycle,
    safely clear of whatever the rising edge just latched, so this can
    poll a multi cycle burst without the read-right-after-RisingEdge
    quirk noted in the other testbenches."""
    bytes_out = []
    for _ in range(max_cycles):
        await FallingEdge(dut.clk)
        if int(dut.data_valid.value) == 1:
            bytes_out.append(int(dut.data_out.value))
            if len(bytes_out) == expected_length:
                break
    return bytes(bytes_out)


async def check_ready_and_no_error(dut):
    await FallingEdge(dut.clk)
    assert int(dut.req_ready.value) == 1, "req_ready should be high once a message has fully gone out"
    assert int(dut.err_valid.value) == 0, "err_valid should not pulse for a message that went out fine"


@cocotb.test()
async def test_enter_order_matches_model(dut):
    await reset_dut(dut)
    expected = ouch.frame(ouch.encode_enter_order(
        user_ref_num=1, side="B", quantity=100, symbol="AAPL", price=50000000,
        clordid="ORDER1",
    ))
    await drive_enter_order(dut, user_ref_num=1, side="B", quantity=100,
                             symbol="AAPL", price=50000000, clordid="ORDER1")
    got = await collect_output(dut, len(expected))
    assert got == expected, f"expected {expected!r}, got {got!r}"
    await check_ready_and_no_error(dut)


@cocotb.test()
async def test_replace_order_matches_model(dut):
    await reset_dut(dut)
    expected = ouch.frame(ouch.encode_replace_order(
        orig_user_ref_num=1, user_ref_num=2, quantity=80, price=49500000,
        clordid="ORDER2",
    ))
    await drive_replace_order(dut, orig_user_ref_num=1, user_ref_num=2,
                               quantity=80, price=49500000, clordid="ORDER2")
    got = await collect_output(dut, len(expected))
    assert got == expected, f"expected {expected!r}, got {got!r}"
    await check_ready_and_no_error(dut)


@cocotb.test()
async def test_cancel_order_matches_model(dut):
    await reset_dut(dut)
    expected = ouch.frame(ouch.encode_cancel_order(user_ref_num=2, quantity=0))
    await drive_cancel_order(dut, user_ref_num=2, quantity=0)
    got = await collect_output(dut, len(expected))
    assert got == expected, f"expected {expected!r}, got {got!r}"
    await check_ready_and_no_error(dut)


@cocotb.test()
async def test_unsupported_request_type_rejected(dut):
    await reset_dut(dut)
    dut.req_valid.value = 1
    dut.msg_type.value = ord("M")  # Modify Order: not implemented here
    await RisingEdge(dut.clk)  # ST_IDLE consumes the request here
    dut.req_valid.value = 0
    await FallingEdge(dut.clk)  # err_valid is valid during this cycle
    assert int(dut.err_valid.value) == 1, "err_valid did not pulse for an unsupported request type"
    assert int(dut.req_ready.value) == 1, "an unsupported request should not leave the encoder busy"


@cocotb.test()
async def test_back_to_back_requests(dut):
    await reset_dut(dut)

    expected1 = ouch.frame(ouch.encode_cancel_order(user_ref_num=5, quantity=0))
    await drive_cancel_order(dut, user_ref_num=5, quantity=0)
    got1 = await collect_output(dut, len(expected1))
    assert got1 == expected1, f"expected {expected1!r}, got {got1!r}"

    expected2 = ouch.frame(ouch.encode_enter_order(
        user_ref_num=6, side="S", quantity=50, symbol="MSFT", price=42000000,
        clordid="ORDER3",
    ))
    await drive_enter_order(dut, user_ref_num=6, side="S", quantity=50,
                             symbol="MSFT", price=42000000, clordid="ORDER3")
    got2 = await collect_output(dut, len(expected2))
    assert got2 == expected2, f"expected {expected2!r}, got {got2!r}"
