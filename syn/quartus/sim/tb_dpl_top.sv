// End-to-end test of syn/quartus/dpl_top.sv through EPT's real Active
// Transfer library: a host model speaks the library's UART framing, sends
// ITCH frames lockstep (one frame, then wait for its reply) and checks
// every 17 byte reply against model/board_link.py's prediction, which
// gen_vectors.py writes out. Then it clears the board over the trigger
// endterm and checks the book really is empty again.
//
// Needs EPT's library in syn/quartus/ept/src/, see the README there.
// Run from the repo root: ./syn/quartus/sim/run_dpl_sim.sh
//
// The library's baud divider is a module parameter, overridden here to keep
// the run short, as the RRC testbench does. The framing and every state
// machine are unchanged.
`timescale 1ns / 1ps
`include "vectors.vh"

module tb_dpl_top;

  localparam logic [2:0] ADDR = 3'h1;

  // 16x oversampling tick every UART_DIV+1 clocks. The board runs 35
  // (66 MHz / 36 / 16 = 114.6 kbaud); 7 is 4.5x faster.
  localparam logic [7:0] UART_DIV = 8'd7;
  localparam int BIT_CYC = 16 * (UART_DIV + 1);

  logic clk = 1'b0;
  always #7.576 clk = ~clk;  // 66 MHz

  logic rst_pin = 1'b0;
  logic host_tx = 1'b1;      // -> UART_IN
  wire  host_rx;             // <- UART_OUT
  wire [3:0] led;

  dpl_top #(
      .CAPACITY    (`CAPACITY),
      .MM_ADDR     (ADDR),
      .RESET_COUNT (12'd40),
      .HEARTBEAT_W (8)
  ) dut (
      .CLK_66MHZ (clk),
      .RST       (rst_pin),
      .UART_IN   (host_tx),
      .UART_OUT  (host_rx),
      .LED       (led)
  );

  defparam dut.u_ept.ACTIVE_TRANSFER_UART_INST.COUNT_TO_DECIMAL_2 = UART_DIV;

  logic [7:0]  frames  [0:`N_FRAME_BYTES-1];
  logic [15:0] lens    [0:`N_FRAMES-1];
  logic [7:0]  replies [0:17*`N_FRAMES-1];

  //------------------------------------------------------------------
  // host side of the EPT framing: {2'b10, cmd, addr} then the payload
  //------------------------------------------------------------------
  task automatic uart_send(input logic [7:0] b);
    host_tx = 1'b0;
    repeat (BIT_CYC) @(posedge clk);
    for (int i = 0; i < 8; i++) begin
      host_tx = b[i];
      repeat (BIT_CYC) @(posedge clk);
    end
    host_tx = 1'b1;
    repeat (BIT_CYC) @(posedge clk);
  endtask

  task automatic send_transfer(input logic [7:0] payload);
    uart_send({2'b10, 3'h2, ADDR});
    uart_send(payload);
  endtask

  task automatic send_trigger(input logic [7:0] bits);
    uart_send({2'b10, 3'h1, 3'h0});
    uart_send(bits);
  endtask

  //------------------------------------------------------------------
  // host receiver: frames -> reply bytes
  //------------------------------------------------------------------
  logic [7:0] rx_q [0:63];
  int n_rx = 0;
  int errors = 0;

  task automatic uart_recv(output logic [7:0] b);
    @(negedge host_rx);
    repeat (BIT_CYC + BIT_CYC / 2) @(posedge clk);
    for (int i = 0; i < 8; i++) begin
      b[i] = host_rx;
      repeat (BIT_CYC) @(posedge clk);
    end
    if (host_rx !== 1'b1) begin
      $display("FAIL: framing error on UART_OUT at %0t", $time);
      errors++;
    end
  endtask

  logic [7:0] hdr, pay;
  always begin
    uart_recv(hdr);
    uart_recv(pay);
    if (hdr !== {2'b11, 3'h2, ADDR}) begin
      $display("FAIL: unexpected frame header %02h", hdr);
      errors++;
    end else begin
      rx_q[n_rx % 64] = pay;
      n_rx++;
    end
  end

  task automatic wait_reply(input int want);
    int guard = 0;
    while (n_rx < want && guard < 60 * 20 * BIT_CYC) begin
      @(posedge clk);
      guard++;
    end
  endtask

  //------------------------------------------------------------------
  // stimulus
  //------------------------------------------------------------------
  int pos = 0;
  int base;
  int bad;
  logic [7:0] got;

  initial begin
    $readmemh("frames.hex", frames);
    $readmemh("lens.hex", lens);
    $readmemh("replies.hex", replies);

    repeat (20) @(posedge clk);
    rst_pin = 1'b1;
    repeat (200) @(posedge clk);

    for (int f = 0; f < `N_FRAMES; f++) begin
      base = n_rx;
      for (int k = 0; k < lens[f]; k++) send_transfer(frames[pos + k]);
      pos += lens[f];
      wait_reply(base + 17);
      // nothing extra may follow a reply
      repeat (40 * BIT_CYC) @(posedge clk);
      if (n_rx != base + 17) begin
        $display("FAIL: frame %0d: got %0d reply bytes, expected 17", f, n_rx - base);
        errors++;
        n_rx = base + 17;
      end
      bad = 0;
      for (int k = 0; k < 17; k++) begin
        got = rx_q[(base + k) % 64];
        if (got !== replies[17 * f + k]) bad++;
      end
      if (bad != 0) begin
        $write("FAIL: frame %0d reply mismatch\n  got ", f);
        for (int k = 0; k < 17; k++) $write("%02h", rx_q[(base + k) % 64]);
        $write("\n  exp ");
        for (int k = 0; k < 17; k++) $write("%02h", replies[17 * f + k]);
        $write("\n");
        errors++;
      end
    end

    // trigger bit 0 clears the book: deleting order 6 (added at the end
    // of the basic session, and possibly still resting) must now fail,
    // with both sides of the book empty
    send_trigger(8'h01);
    repeat (4 * BIT_CYC) @(posedge clk);
    base = n_rx;
    // D message for order_ref 1: 2 byte length then a 19 byte body
    send_transfer(8'h00); send_transfer(8'h13);
    send_transfer("D");
    for (int k = 0; k < 18; k++) send_transfer(k == 18 - 1 ? 8'h01 : 8'h00);
    wait_reply(base + 17);
    if (n_rx != base + 17) begin
      $display("FAIL: after clear, got %0d reply bytes, expected 17", n_rx - base);
      errors++;
    end
    // status: marker, book_err, nothing else; all prices and quantities 0
    if (rx_q[base % 64] !== 8'h82) begin
      $display("FAIL: after clear, status %02h expected 82", rx_q[base % 64]);
      errors++;
    end
    for (int k = 1; k < 17; k++)
      if (rx_q[(base + k) % 64] !== 8'h00) begin
        $display("FAIL: after clear, reply byte %0d is %02h", k, rx_q[(base + k) % 64]);
        errors++;
      end

    if (dut.overrun) begin
      $display("FAIL: the bridge saw an overrun");
      errors++;
    end

    $display("");
    $display("dpl_top through the EPT library:");
    $display("  frames          : %0d (+1 after clear)", `N_FRAMES);
    $display("  reply bytes back: %0d", n_rx);
    $display("  failures        : %0d", errors);
    if (errors == 0) $display("PASS");
    else             $display("FAIL");
    $finish;
  end

  initial begin
    if ($test$plusargs("dump")) begin
      $dumpfile("tb_dpl_top.vcd");
      $dumpvars(0, tb_dpl_top);
    end
  end

endmodule
