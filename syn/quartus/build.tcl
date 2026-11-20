# Quartus project + compile for the market maker on the EPT DueProLogic
# (Cyclone IV E EP4CE6E22C8): syn/quartus/dpl_top.sv, which wraps
# market_maker_top (ITCH decode + order book) in rtl/board/mm_bridge.sv and
# talks to the PC through EPT's Active Transfer library. Produces a .sof
# (JTAG) and a .pof for the board's configuration flash (EPT-Blaster,
# Active Serial).
#
# Based on the RRC filter project's hw_demo/dpl/build.tcl, which built and
# ran on this board with Quartus Prime 25.1std Lite.
#
# Run from the repository root, after copying EPT's library into
# syn/quartus/ept/src/ (see syn/quartus/ept/README.md):
#     quartus_sh -t syn/quartus/build.tcl            (or: make synth-quartus)
#
# options:
#     -capacity N                  order book entries (default 8)
#     -config-device EPCS4|EPCS1   flash the .pof targets (default EPCS4)
#     -out <dir>                   output directory (default syn/quartus/output)

package require ::quartus::project
package require ::quartus::flow

set project_name  "market_maker_dpl"
set top_level     "dpl_top"
set device        "EP4CE6E22C8"
set family        "Cyclone IV E"
set out_dir       "syn/quartus/output"
set ept_dir       "syn/quartus/ept/src"
set capacity      8
# The board's datasheet lists the flash as an M25P40, which is an EPCS4.
# EPT's own demo projects say EPCS1; if the Programmer rejects the flash's
# silicon ID, rebuild with -config-device EPCS1.
set config_device "EPCS4"

for {set i 0} {$i < [llength $quartus(args)]} {incr i} {
    set arg [lindex $quartus(args) $i]
    switch -- $arg {
        -capacity      { incr i; set capacity      [lindex $quartus(args) $i] }
        -config-device { incr i; set config_device [lindex $quartus(args) $i] }
        -out           { incr i; set out_dir       [lindex $quartus(args) $i] }
    }
}

# EPT's library is not in the repo. Fail here with a useful message rather
# than in Analysis & Synthesis with a missing-module error.
set ept_files {
    active_serial_library.v
    active_transfer_uart.v
    ft_245_state_machine.v
    endpoint_registers.v
    active_trigger.v
    active_transfer.v
    uart_top.v
    uart_receiver.v
    uart_transmitter.v
    eptWireOR.v
}
foreach f [concat $ept_files define.v] {
    if {![file exists "$ept_dir/$f"]} {
        post_message -type error "missing $ept_dir/$f: copy EPT's Active Transfer library there, see syn/quartus/ept/README.md"
        qexit -error
    }
}

file mkdir $out_dir

# the .qpf/.qsf are written to the repo root (git-ignored), as in the RRC
# build, so every path below is relative to the root
if {[project_exists $project_name]} {
    project_open $project_name -revision $project_name
} else {
    project_new $project_name -revision $project_name -overwrite
}

set_global_assignment -name FAMILY $family
set_global_assignment -name DEVICE $device
set_global_assignment -name TOP_LEVEL_ENTITY $top_level
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY $out_dir

# the market maker RTL is SystemVerilog; EPT's library is Verilog 2001
set_global_assignment -name VERILOG_INPUT_VERSION SYSTEMVERILOG_2005
set_global_assignment -name SEARCH_PATH $ept_dir

foreach f {
    rtl/decode/itch_decode.sv
    rtl/book/order_book.sv
    rtl/top/market_maker_top.sv
    rtl/board/mm_bridge.sv
    syn/quartus/dpl_top.sv
} {
    set_global_assignment -name SYSTEMVERILOG_FILE $f
}
# eptWireOR.v ends with `default_nettype none, keep it last
foreach f $ept_files {
    set_global_assignment -name VERILOG_FILE "$ept_dir/$f"
}

set_parameter -name CAPACITY $capacity

set_global_assignment -name SDC_FILE syn/quartus/market_maker.sdc
source syn/quartus/dpl_pins.tcl

# configuration: Active Serial from the on-board flash, programmed by
# EPT-Blaster. Setting the configuration device makes the Assembler write
# the .pof next to the .sof.
set_global_assignment -name USE_CONFIGURATION_DEVICE ON
set_global_assignment -name CYCLONEIII_CONFIGURATION_DEVICE $config_device
set_global_assignment -name ON_CHIP_BITSTREAM_DECOMPRESSION ON
set_global_assignment -name CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION "USE AS REGULAR IO"
# unused pins include the other 32 LEDs and the rest of the FT2232H bus:
# leave them as inputs with weak pull-ups, which keeps the LEDs dark
set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED WITH WEAK PULL-UP"

set_global_assignment -name OPTIMIZATION_MODE "HIGH PERFORMANCE EFFORT"
set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL

execute_module -tool map
execute_module -tool fit
execute_module -tool sta
execute_module -tool asm

project_close

puts ""
puts "Compile finished (CAPACITY = $capacity)."
puts "  fit report : $out_dir/${project_name}.fit.summary"
puts "  sta report : $out_dir/${project_name}.sta.rpt"
puts "  JTAG image : $out_dir/${project_name}.sof"
puts "  flash image: $out_dir/${project_name}.pof  ($config_device, program with EPT-Blaster in Active Serial mode)"
