# Timing constraints for the DueProLogic board top (syn/quartus/dpl_top.sv).
# Everything runs off the 66 MHz oscillator, the clock EPT's Active
# Transfer library is written for (its baud divider assumes it).

create_clock -name clk66 -period 15.151 [get_ports CLK_66MHZ]

derive_clock_uncertainty

# UART_IN goes through a 3-flop synchroniser, RST is an async reset into a
# counter, and the LEDs and UART_OUT are seen by nothing that cares about
# nanoseconds. None of these are timed.
set_false_path -from [get_ports {RST UART_IN}]
set_false_path -to   [get_ports {UART_OUT LED[*]}]
