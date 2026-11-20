# EPT Active Transfer library goes here

`syn/quartus/dpl_top.sv` talks to the PC through Earth People Technology's
Active Transfer library. It is EPT's copyrighted code from the DueProLogic
package, so it is not committed. Copy it in before building or simulating:

```
syn/quartus/ept/src/
    active_serial_library.v   UART flavour of the library (USB-C board rev)
    active_transfer_uart.v
    ft_245_state_machine.v
    endpoint_registers.v
    active_trigger.v
    active_transfer.v
    uart_top.v
    uart_receiver.v
    uart_transmitter.v
    eptWireOR.v
    define.v                  included by the others as "../src/define.v"
```

These are the same files the RRC filter project uses. From Git Bash at the
repo root, copying from that project:

```bash
mkdir -p syn/quartus/ept/src
cp /c/Users/<you>/Documents/GFPGA/rrc-matched-filter/hw_demo/dpl/ept/src/*.v syn/quartus/ept/src/
```

or from the package itself:
`DUEPROLOGIC_USB_FPGA_PROJECT_5.1_DVD/Projects_HDL/EPT_4CE6_AF_Platform_Demo/src/`.

The folder has to be called `src`: every library file does
`` `include "../src/define.v" ``. Use `active_serial_library`, not the older
`active_transfer_library` from the user manual: the USB-C board runs the
FT2232H as a UART.

Everything in this folder except this README is ignored by git.
