SIM ?= verilator
TOPLEVEL_LANG := verilog

VERILOG_SOURCES := ../../rtl/book/order_book.sv
COCOTB_TOPLEVEL := order_book
COCOTB_TEST_MODULES := test_book

# small table on purpose, so a test can actually fill it up
EXTRA_ARGS += -GCAPACITY=4

include $(shell cocotb-config --makefiles)/Makefile.sim
