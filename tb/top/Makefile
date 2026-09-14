SIM ?= verilator
TOPLEVEL_LANG := verilog

VERILOG_SOURCES := ../../rtl/decode/itch_decode.sv ../../rtl/book/order_book.sv ../../rtl/top/market_maker_top.sv
COCOTB_TOPLEVEL := market_maker_top
COCOTB_TEST_MODULES := test_top

# small table on purpose, so a test can actually fill it up
EXTRA_ARGS += -GCAPACITY=4

include $(shell cocotb-config --makefiles)/Makefile.sim
