`default_nettype none

// Board top level for the EPT DueProLogic (EPT-4CE6-AF-D2, USB-C rev,
// EP4CE6E22C8N): the market maker (ITCH decode + order book) driven over
// USB through EPT's Active Transfer library.
//
//   PC --USB--> FT2232H --UART 115200--> active_serial_library
//      --> active_transfer @ MM_ADDR --> raw ITCH bytes --> mm_bridge
//      --> 17 byte reply per frame --> active_transfer --> back to PC
//
// The reply format is described in rtl/board/mm_bridge.sv. On the wire
// each Active Transfer is two UART bytes, a header {2'b10|2'b11, cmd[2:0],
// addr[2:0]} and then the payload byte.
//
// Host trigger bit 0 clears the order book and resynchronises framing.
//
// The host must run lockstep: send one whole ITCH frame, wait for its 17
// byte reply, then send the next. Inside EPT's library the UART receiver
// and the write path share one tri-state byte bus, so a byte arriving
// while a reply frame is going out gets corrupted (found in the RRC filter
// project's testbench). mm_bridge never starts a reply before the last
// byte of a frame is in, and scripts/dpl_host.py waits for the full reply.
//
// The structure (power-on reset, UART synchroniser, transmit handshake on
// the endpoint busy bit) follows the RRC filter's hw_demo/dpl/dpl_top.v,
// which ran on this board. EPT's library is not in this repo, see
// syn/quartus/ept/README.md. Port names follow EPT's own top level so
// their pinout carries over unchanged.

module dpl_top #(
    parameter int          CAPACITY     = 8,
    parameter logic [2:0]  MM_ADDR      = 3'h1,
    parameter logic [11:0] RESET_COUNT  = 12'h9c8,   // power-on reset, same as EPT's demo
    parameter int          HEARTBEAT_W  = 26,        // 66 MHz / 2^26 ~ 1 Hz blink
    parameter logic [19:0] BUSY_TIMEOUT = 20'hfffff  // ~16 ms, escape hatch if the library never answers
) (
    input  wire logic       CLK_66MHZ,  // PIN_23, 66 MHz oscillator on GCLK1
    input  wire logic       RST,        // PIN_89, pulled up on the board, low = reset

    input  wire logic       UART_IN,    // PIN_43, FT2232H BDBUS0 (TXD) -> FPGA
    output wire logic       UART_OUT,   // PIN_38, FPGA -> FT2232H BDBUS1 (RXD)

    output wire logic [3:0] LED         // LED0..3 of the 6x6 array, active low
);

  // the library holds start_transfer for its own 3-cycle window, give it 4
  localparam logic [2:0] START_HOLD = 3'd4;

  //------------------------------------------------------------------
  // reset: counter released by RST, as EPT's demo does it. rst_n drives
  // the library; our own logic takes a synchronous active-high copy.
  //------------------------------------------------------------------
  logic [11:0] reset_counter;
  logic        rst_n;

  always_ff @(posedge CLK_66MHZ or negedge RST) begin
    if (!RST) begin
      reset_counter <= 12'd0;
      rst_n         <= 1'b0;
    end else if (reset_counter < RESET_COUNT) begin
      reset_counter <= reset_counter + 12'd1;
      rst_n         <= 1'b0;
    end else begin
      rst_n         <= 1'b1;
    end
  end

  logic rst;
  always_ff @(posedge CLK_66MHZ) rst <= ~rst_n;

  // UART_IN is asynchronous to CLK_66MHZ; the idle line is high
  logic [2:0] uart_sync;
  always_ff @(posedge CLK_66MHZ) begin
    if (rst) uart_sync <= 3'b111;
    else     uart_sync <= {uart_sync[1:0], UART_IN};
  end

  //------------------------------------------------------------------
  // EPT Active Transfer library and endterms
  //------------------------------------------------------------------
  wire [1:0]      aa = {CLK_66MHZ, rst_n};
  wire [23:0]     UC_IN;
  wire [21:0]     UC_OUT;
  wire [2*22-1:0] uc_out_m;

  active_serial_library u_ept (
      .aa        (aa),
      .UART_OUT  (UART_OUT),
      .UART_IN   (uart_sync[2]),
      .UC_IN     (UC_IN),
      .UC_OUT    (UC_OUT),
      .STATE_OUT (),
      .TEST_OUT  ()
  );

  eptWireOR #(.N(2)) u_uc_or (UC_OUT, uc_out_m);

  wire [7:0] trigger_from_host;

  active_trigger u_trigger (
      .uc_clk            (CLK_66MHZ),
      .uc_reset          (rst_n),
      .uc_in             (UC_IN),
      .uc_out            (uc_out_m[0*22 +: 22]),
      .trigger_to_host   (8'h00),
      .trigger_to_device (trigger_from_host)
  );

  logic      tx_start;
  logic [7:0] ept_tx_byte;
  wire       rx_received;
  wire [7:0] ept_rx_byte;

  active_transfer u_bytes (
      .uc_clk             (CLK_66MHZ),
      .uc_reset           (rst_n),
      .uc_in              (UC_IN),
      .uc_out             (uc_out_m[1*22 +: 22]),
      .start_transfer     (tx_start),
      .transfer_received  (rx_received),
      // transfer_busy also latches on every received byte and only clears
      // after the next send, so it can't gate sends; the endpoint busy bit
      // on UC_IN is used instead (as in the RRC build)
      .transfer_busy      (),
      .uc_addr            (MM_ADDR),
      .transfer_to_host   (ept_tx_byte),
      .transfer_to_device (ept_rx_byte)
  );

  // UC_IN[23]: the library's endpoint is busy writing a frame to the host
  wire ept_busy = UC_IN[23];

  //------------------------------------------------------------------
  // host trigger bit 0 -> clear. trigger_to_device is combinational off
  // UC_IN and only lasts a few cycles, so edge-detect it.
  //------------------------------------------------------------------
  logic trig0_d, clear;
  always_ff @(posedge CLK_66MHZ) begin
    if (rst) begin
      trig0_d <= 1'b0;
      clear   <= 1'b0;
    end else begin
      trig0_d <= trigger_from_host[0];
      clear   <= trigger_from_host[0] & ~trig0_d;
    end
  end

  // transfer_received is high for two cycles: one strobe per byte
  logic rx_received_d;
  logic rx_strobe;
  logic [7:0] rx_byte_q;
  always_ff @(posedge CLK_66MHZ) begin
    if (rst) begin
      rx_received_d <= 1'b0;
      rx_strobe     <= 1'b0;
      rx_byte_q     <= 8'h00;
    end else begin
      rx_received_d <= rx_received;
      rx_strobe     <= rx_received & ~rx_received_d;
      if (rx_received & ~rx_received_d) rx_byte_q <= ept_rx_byte;
    end
  end

  //------------------------------------------------------------------
  // the market maker behind a byte-stream bridge
  //------------------------------------------------------------------
  logic       br_tx_valid, br_tx_ready;
  logic [7:0] br_tx_byte;
  logic       reply_start, any_err, overrun;

  mm_bridge #(
      .CAPACITY(CAPACITY)
  ) u_bridge (
      .clk        (CLK_66MHZ),
      .rst        (rst),
      .clear      (clear),
      .rx_valid   (rx_strobe),
      .rx_byte    (rx_byte_q),
      .tx_valid   (br_tx_valid),
      .tx_byte    (br_tx_byte),
      .tx_ready   (br_tx_ready),
      .reply_start(reply_start),
      .any_err    (any_err),
      .overrun    (overrun)
  );

  //------------------------------------------------------------------
  // reply bytes -> host. Per byte: take it from the bridge, hold
  // start_transfer for START_HOLD cycles, then wait for the endpoint to go
  // busy and idle again, which is when the frame has been handed to the
  // UART. A second start while the endpoint is busy would be dropped
  // silently, hence the wait.
  //------------------------------------------------------------------
  typedef enum logic [1:0] {
    TX_IDLE,
    TX_START,
    TX_BUSY
  } tx_state_e;

  tx_state_e   tx_state;
  logic [2:0]  hold_cnt;
  logic        seen_busy;
  logic [19:0] busy_timer;

  assign br_tx_ready = (tx_state == TX_IDLE) && br_tx_valid && !clear;

  always_ff @(posedge CLK_66MHZ) begin
    if (rst || clear) begin
      tx_state    <= TX_IDLE;
      hold_cnt    <= 3'd0;
      seen_busy   <= 1'b0;
      busy_timer  <= 20'd0;
      tx_start    <= 1'b0;
      ept_tx_byte <= 8'h00;
    end else begin
      case (tx_state)
        TX_IDLE: begin
          tx_start <= 1'b0;
          if (br_tx_ready) begin
            ept_tx_byte <= br_tx_byte;
            hold_cnt    <= 3'd0;
            tx_state    <= TX_START;
          end
        end
        TX_START: begin
          tx_start <= 1'b1;
          hold_cnt <= hold_cnt + 3'd1;
          if (hold_cnt == START_HOLD - 3'd1) begin
            seen_busy  <= 1'b0;
            busy_timer <= 20'd0;
            tx_state   <= TX_BUSY;
          end
        end
        TX_BUSY: begin
          tx_start   <= 1'b0;
          busy_timer <= busy_timer + 20'd1;
          if (ept_busy) seen_busy <= 1'b1;
          if ((seen_busy && !ept_busy) || busy_timer == BUSY_TIMEOUT) tx_state <= TX_IDLE;
        end
        default: tx_state <= TX_IDLE;
      endcase
    end
  end

  //------------------------------------------------------------------
  // LEDs, active low (sunk by the FPGA through 220R to 3V3)
  //   LED0 heartbeat: clock running and out of reset
  //   LED1 toggles on every frame answered
  //   LED2 a decode or book error, or an overrun, since the last clear
  //   LED3 overrun: the host sent a byte while a reply was going out
  //------------------------------------------------------------------
  logic [HEARTBEAT_W-1:0] heartbeat;
  logic                   reply_toggle;

  always_ff @(posedge CLK_66MHZ) begin
    if (rst) begin
      heartbeat    <= '0;
      reply_toggle <= 1'b0;
    end else begin
      heartbeat <= heartbeat + 1'b1;
      if (reply_start) reply_toggle <= ~reply_toggle;
    end
  end

  assign LED = ~{overrun, any_err, reply_toggle, heartbeat[HEARTBEAT_W-1]};

endmodule

`default_nettype wire
