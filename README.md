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
rtl/board     byte-stream bridge that puts the top level on a board link
tb            cocotb testbenches, one directory per module
model         Python golden model used to check the RTL
syn/xdc       timing and pin constraints
syn/quartus   Quartus build for the EPT DueProLogic (Cyclone IV)
scripts       host scripts that talk to the board
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

Running on the DueProLogic

The design runs on an EPT DueProLogic (EPT-4CE6-AF-D2, USB-C rev), a Cyclone
IV E EP4CE6E22C8 board, built with Quartus Prime 25.1std Lite on Windows.
The EP4CE6 has 6,272 logic elements, so the order book goes on it with 8
entries; 64 entries need the book moved into block RAM first.

    syn/quartus/dpl_top.sv        board top: USB bytes -> mm_bridge -> USB bytes, LEDs
    rtl/board/mm_bridge.sv        ITCH frames in, one 17 byte reply out per frame
    syn/quartus/build.tcl         Quartus project + compile, writes .sof and .pof
    syn/quartus/dpl_pins.tcl      pins, from the RRC filter build on this board
    syn/quartus/market_maker.sdc  66 MHz clock
    syn/quartus/sim/              board top through EPT's real library
    scripts/dpl_host.py           sends frames over the COM port, checks replies

The PC sends raw ITCH frames (2 byte length, then the body) over EPT's
Active Transfer link. After each frame the board answers with 17 bytes: a
status byte (decode error, book error, update, bid/ask valid, overrun),
then best bid price and quantity and best ask price and quantity, all
big-endian. rtl/board/mm_bridge.sv documents the format. The host must
send one frame and wait for its reply before sending the next.

EPT's library is their code and is not in the repo. Copy it into
syn/quartus/ept/src/ first, see syn/quartus/ept/README.md. Then:

    make sim-dpl                  simulate the board top through EPT's library
    make synth-quartus            compile; QUARTUS_SH can point at quartus_sh.exe

To program: in the Quartus Programmer pick EPT-Blaster, mode Active Serial
Programming, add syn/quartus/output/market_maker_dpl.pof and start. If the
Programmer rejects the flash ID, rebuild with -config-device EPCS1. The
USB-C port can't do JTAG, so loading the .sof directly needs a USB-Blaster
on the JTAG header.

Then, with pyserial installed and the UART COM port's latency timer at 1 ms:

    python scripts/dpl_host.py --port COM14 --random 2000

LEDs (active low): LED0 heartbeat, LED1 toggles per reply, LED2 any decode
or book error since the last clear, LED3 overrun (the host sent a byte
while a reply was still going out).

