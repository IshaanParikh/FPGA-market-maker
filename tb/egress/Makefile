SIM ?= verilator
TOPLEVEL_LANG := verilog

VERILOG_SOURCES := ../../rtl/egress/ouch_encode.sv
COCOTB_TOPLEVEL := ouch_encode
COCOTB_TEST_MODULES := test_ouch_encode

include $(shell cocotb-config --makefiles)/Makefile.sim
