# Build for the ITCH decode / order book / OUCH egress project.
# Tools run under WSL, so from Windows use: wsl make lint

SHELL := /bin/bash

# --- Layout ---------------------------------------------------------------
RTL_DIRS := rtl/common rtl/decode rtl/book rtl/egress rtl/top
RTL_SRCS := $(sort $(foreach d,$(RTL_DIRS),$(wildcard $(d)/*.sv)))
INCDIRS  := $(addprefix -y ,$(RTL_DIRS)) $(addprefix -I,$(RTL_DIRS))
TB_DIRS  := $(patsubst %/,%,$(sort $(dir $(wildcard tb/*/Makefile))))
TB_NAMES := $(notdir $(TB_DIRS))

# --- Simulator ------------------------------------------------------------
# Verilator by default. Override to cross-check: make sim MOD=x SIM=icarus
SIM ?= verilator

# Verilator writes thousands of small files, which is ~26x slower on /mnt/c
# than on ext4. Move the build tree off the Windows mount if needed:
#   make sim MOD=itch_decode BUILD_ROOT=~/.cache/fpga-mm
BUILD_ROOT ?= $(CURDIR)

# No -Wno-fatal: warnings must fail the build, not scroll past.
VERILATOR_LINT_FLAGS := --lint-only -Wall --timing

.PHONY: all lint sim sim-all model-check synth tools-check clean help

all: help

# --- Lint -----------------------------------------------------------------
lint:
	@if [ -z "$(RTL_SRCS)" ]; then \
	  echo "lint: no .sv sources under rtl/ yet - nothing to check."; \
	else \
	  echo "lint: $(words $(RTL_SRCS)) source(s)"; \
	  verilator $(VERILATOR_LINT_FLAGS) $(INCDIRS) $(RTL_SRCS); \
	  echo "lint: clean"; \
	fi

# --- Single-module simulation ---------------------------------------------
# Each DUT has tb/<mod>/Makefile including cocotb's Makefile.sim.
sim:
	@if [ -z "$(MOD)" ]; then \
	  echo "usage: make sim MOD=<module>"; \
	  if [ -n "$(TB_NAMES)" ]; then echo "available: $(TB_NAMES)"; \
	  else echo "(no testbenches under tb/ yet)"; fi; \
	  exit 2; \
	fi
	@if [ ! -d "tb/$(MOD)" ]; then \
	  echo "sim: no testbench directory tb/$(MOD)/"; exit 2; \
	fi
	$(MAKE) -C tb/$(MOD) SIM=$(SIM) SIM_BUILD="$(BUILD_ROOT)/sim_build/$(MOD)"

# --- Full regression ------------------------------------------------------
# One shell invocation on purpose: split in two, an early exit only leaves the
# first subshell and the second still prints a pass for a run that did nothing.
# An empty tb/ is a failure here, not a pass.
sim-all:
	@if [ -z "$(TB_DIRS)" ]; then \
	  echo "sim-all: no testbenches under tb/ - refusing to report a pass."; \
	  exit 1; \
	fi; \
	fail=""; \
	for d in $(TB_DIRS); do \
	  m=$$(basename $$d); \
	  echo "=== $$m ==="; \
	  $(MAKE) -C $$d SIM=$(SIM) SIM_BUILD="$(BUILD_ROOT)/sim_build/$$m" || fail="$$fail $$m"; \
	done; \
	if [ -n "$$fail" ]; then echo "sim-all: FAILED:$$fail"; exit 1; fi; \
	echo "sim-all: all green ($(words $(TB_DIRS)) testbench(es))"

# --- Golden model ---------------------------------------------------------
model-check:
	@if [ ! -f model/selftest.py ]; then \
	  echo "model-check: model/selftest.py does not exist yet."; exit 2; \
	fi
	python3 model/selftest.py

# --- Synthesis ------------------------------------------------------------
synth:
	@if ! command -v vivado >/dev/null 2>&1; then \
	  echo "synth: vivado is not on PATH."; exit 2; \
	fi
	@if [ ! -f syn/build.tcl ]; then \
	  echo "synth: syn/build.tcl does not exist yet."; exit 2; \
	fi
	cd syn && vivado -mode batch -source build.tcl -nojournal -log reports/vivado.log

# --- Environment ----------------------------------------------------------
# Reports what is installed. Does not install anything.
tools-check:
	@echo "--- toolchain ---"
	@for t in verilator iverilog make python3 vivado; do \
	  printf "%-12s " "$$t"; \
	  command -v $$t >/dev/null 2>&1 && command -v $$t || echo "NOT FOUND"; \
	done
	@printf "%-12s " "cocotb"; \
	python3 -c "import cocotb; print(cocotb.__version__)" 2>/dev/null || echo "NOT FOUND"
	@echo "--- sources ---"
	@echo "rtl : $(words $(RTL_SRCS)) file(s)"
	@echo "tb  : $(words $(TB_DIRS)) testbench(es)"

clean:
	rm -rf "$(BUILD_ROOT)/sim_build" obj_dir results.xml
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

help:
	@echo "make lint            Verilator lint over rtl/ (zero warnings required)"
	@echo "make sim MOD=<name>  cocotb test for one module"
	@echo "make sim-all         full regression"
	@echo "make model-check     golden model self-test"
	@echo "make synth           Vivado synth + P&R into syn/reports/"
	@echo "make tools-check     report which tools are installed"
