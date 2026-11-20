#!/usr/bin/env bash
# DueProLogic board top through EPT's real Active Transfer library, end to
# end, on Icarus Verilog. Run from the repo root:
#     ./syn/quartus/sim/run_dpl_sim.sh          (or: make sim-dpl)
#
# Needs EPT's library copied into syn/quartus/ept/src/ (see the README
# there). Not part of sim-all, because that library isn't in the repo.
# env overrides: IVERILOG, VVP, PYTHON, DUMP=1
set -euo pipefail

cd "$(dirname "$0")/../../.."

PYTHON="${PYTHON:-python3}"
IVERILOG="${IVERILOG:-iverilog}"
VVP="${VVP:-vvp}"

EPT="syn/quartus/ept/src"
EPT_FILES="active_serial_library.v active_transfer_uart.v ft_245_state_machine.v
           endpoint_registers.v active_trigger.v active_transfer.v
           uart_top.v uart_receiver.v uart_transmitter.v eptWireOR.v"

for f in $EPT_FILES define.v; do
    if [ ! -f "$EPT/$f" ]; then
        echo "missing $EPT/$f - copy EPT's Active Transfer library there first," >&2
        echo "see syn/quartus/ept/README.md" >&2
        exit 1
    fi
done

BUILD="syn/quartus/sim/build"
mkdir -p "$BUILD"
"$PYTHON" syn/quartus/sim/gen_vectors.py --outdir "$BUILD"

RTL="rtl/decode/itch_decode.sv rtl/book/order_book.sv rtl/top/market_maker_top.sv
     rtl/board/mm_bridge.sv syn/quartus/dpl_top.sv"

# eptWireOR.v ends with `default_nettype none, so it goes last
EPT_SRCS=""
for f in $EPT_FILES; do EPT_SRCS="$EPT_SRCS $EPT/$f"; done

PLUS=""
[ "${DUMP:-0}" = "1" ] && PLUS="+dump"

"$IVERILOG" -g2012 -I "$EPT" -I "$BUILD" -o "$BUILD/tb_dpl_top.vvp" \
    syn/quartus/sim/tb_dpl_top.sv $RTL $EPT_SRCS
cd "$BUILD"
"$VVP" -n tb_dpl_top.vvp $PLUS | tee sim.log
grep -q '^PASS$' sim.log
