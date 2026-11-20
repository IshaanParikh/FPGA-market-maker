SIM ?= verilator
TOPLEVEL_LANG := verilog

VERILOG_SOURCES := ../../rtl/decode/itch_decode.sv ../../rtl/book/order_book.sv \
                   ../../rtl/top/market_maker_top.sv ../../rtl/board/mm_bridge.sv
COCOTB_TOPLEVEL := mm_bridge
COCOTB_TEST_MODULES := test_mm_bridge

# 8 entries, the size that goes on the DueProLogic first
EXTRA_ARGS += -GCAPACITY=8

include $(shell cocotb-config --makefiles)/Makefile.sim
