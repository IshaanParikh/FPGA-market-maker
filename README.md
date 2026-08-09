FPGA Market Maker

An FPGA design that reads a market data feed, keeps an order book in hardware,
and sends orders back out. The three main pieces are an ITCH feed decoder, an
order book, and an OUCH egress path.

Status

This is early. The build system and the directory layout are in place. No RTL,
no testbenches, and no golden model have been written yet.

Layout

rtl/common    shared modules
rtl/decode    ITCH feed decoder
rtl/book      order book
rtl/egress    OUCH order output
rtl/top       top level that wires the blocks together
tb            cocotb testbenches, one directory per module
model         Python golden model used to check the RTL
syn/xdc       timing and pin constraints
syn/reports   synthesis and timing reports, checked in on purpose
docs          notes and design docs

Tools

The toolchain runs under WSL, not Windows. You need Verilator for lint and
simulation, cocotb for the testbenches, Python 3 for the golden model, and
Vivado if you want to run synthesis. Icarus Verilog is optional and only used
to re-run a testbench on a second simulator as a cross check.

To see what is installed, run:

    wsl make tools-check

Building

All commands run through make from the repo root. From a Windows shell, put
wsl in front of them.

    wsl make lint              Verilator lint over rtl, must be warning free
    wsl make sim MOD=name      run the cocotb test for one module
    wsl make sim-all           run every testbench
    wsl make model-check       run the golden model self test
    wsl make synth             Vivado synthesis and place and route
    wsl make clean             delete build output

Verilator writes a lot of small files, and that is slow on the Windows drive.
If a build feels sluggish, move the build tree onto the Linux filesystem:

    wsl make sim MOD=itch_decode BUILD_ROOT=~/.cache/fpga-mm

Notes

Line endings are forced to LF through .gitattributes. GNU make will not accept
a recipe with CRLF line endings, and Verilator reports odd errors on them, so
do not turn that off.

A module counts as done when lint is clean with zero warnings, its own
testbench passes, and the full regression is still green.
