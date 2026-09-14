SIM ?= verilator
TOPLEVEL_LANG := verilog

VERILOG_SOURCES := ../../rtl/decode/itch_decode.sv
COCOTB_TOPLEVEL := itch_decode
COCOTB_TEST_MODULES := test_itch_decode

include $(shell cocotb-config --makefiles)/Makefile.sim
