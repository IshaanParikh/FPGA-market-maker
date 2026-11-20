`default_nettype none

// Byte-stream wrapper around market_maker_top, so the whole design can be
// driven from a PC over a plain byte link (on the DueProLogic, EPT's
// Active Transfer UART; see syn/quartus/dpl_top.sv).
//
// Host to board: raw ITCH frames, exactly what itch_decode expects (2 byte
// big-endian length, then the body), one byte per rx_valid pulse.
//
// Board to host: once a whole frame has arrived and the pipeline has
// settled, one 17 byte reply, every multi-byte field big-endian like ITCH:
//
//   byte 0      status
//                 [7:6] 2'b10, a fixed marker so the host can spot a
//                       misaligned reply
//                 [5]   overrun: a byte arrived while a reply was still
//                       going out, and was dropped (sticky until clear)
//                 [4]   ask_valid
//                 [3]   bid_valid
//                 [2]   book_update pulsed for this frame
//                 [1]   book_err pulsed for this frame
//                 [0]   decode_err pulsed for this frame
//   bytes 1-4   bid_price
//   bytes 5-8   bid_qty
//   bytes 9-12  ask_price
//   bytes 13-16 ask_qty
//
// This module tracks the frame length itself, the same way itch_decode
// does, so it knows when the host has finished a frame without waiting on
// anything inside the decoder. That matters on the DueProLogic: EPT's
// library garbles bytes if a reply starts going out while the host is
// still sending, so the reply must not start until the last byte is in.
// The host must run lockstep: send one frame, read its 17 byte reply,
// then send the next.
//
// clear resets the market maker and this module's framing back to the
// start of a frame, so a host can always resynchronise.

module mm_bridge #(
    parameter int CAPACITY = 8,
    // cycles to wait after the last byte of a frame before the result is
    // sampled. The chain is: registered byte into itch_decode (1), its
    // decode state (1), msg_valid/err_valid (1), order_book (1). 8 leaves
    // margin.
    parameter int SETTLE = 8
) (
    input  wire logic       clk,
    input  wire logic       rst,
    input  wire logic       clear,

    input  wire logic       rx_valid,
    input  wire logic [7:0] rx_byte,

    output logic            tx_valid,
    output logic [7:0]      tx_byte,
    input  wire logic       tx_ready,

    // status for LEDs
    output logic            reply_start,  // pulses when a reply is queued
    output logic            any_err,      // sticky: any decode/book error or overrun
    output logic            overrun       // sticky: a byte was dropped
);

  localparam int REPLY_BYTES = 17;
  localparam int SETTLE_W    = $clog2(SETTLE + 1);

  typedef enum logic [2:0] {
    ST_LEN_HI,
    ST_LEN_LO,
    ST_BODY,
    ST_SETTLE,
    ST_SEND
  } state_e;

  state_e      state;
  logic [7:0]  len_hi;
  logic [15:0] frame_len;
  logic [15:0] byte_cnt;
  logic [SETTLE_W-1:0] settle_cnt;
  logic [4:0]  tx_idx;
  logic [8*REPLY_BYTES-1:0] reply;

  // what this frame did, collected while it settles
  logic seen_decode_err, seen_book_err, seen_book_update;

  // market maker, held in reset by clear as well
  logic        core_rst;
  logic [7:0]  core_data;
  logic        core_valid;

  logic        decode_err, book_update, book_err;
  logic        bid_valid, ask_valid;
  logic [31:0] bid_price, bid_qty, ask_price, ask_qty;

  assign core_rst = rst | clear;

  market_maker_top #(
      .CAPACITY(CAPACITY)
  ) u_mm (
      .clk        (clk),
      .rst        (core_rst),
      .data_in    (core_data),
      .valid_in   (core_valid),
      .decode_err (decode_err),
      .book_update(book_update),
      .book_err   (book_err),
      .bid_valid  (bid_valid),
      .bid_price  (bid_price),
      .bid_qty    (bid_qty),
      .ask_valid  (ask_valid),
      .ask_price  (ask_price),
      .ask_qty    (ask_qty)
  );

  // a byte is taken into the current frame only in the three receive
  // states; anything else arriving is dropped and flagged
  logic rx_take;
  assign rx_take = rx_valid && (state == ST_LEN_HI || state == ST_LEN_LO || state == ST_BODY);

  assign tx_valid = (state == ST_SEND);
  assign tx_byte  = reply[8*REPLY_BYTES-1 -: 8];

  always_ff @(posedge clk) begin
    reply_start <= 1'b0;

    if (core_rst) begin
      state            <= ST_LEN_HI;
      len_hi           <= '0;
      frame_len        <= '0;
      byte_cnt         <= '0;
      settle_cnt       <= '0;
      tx_idx           <= '0;
      reply            <= '0;
      core_data        <= '0;
      core_valid       <= 1'b0;
      seen_decode_err  <= 1'b0;
      seen_book_err    <= 1'b0;
      seen_book_update <= 1'b0;
      any_err          <= 1'b0;
      overrun          <= 1'b0;
    end else begin
      // forward accepted bytes to the decoder, registered
      core_valid <= rx_take;
      if (rx_take) core_data <= rx_byte;

      if (rx_valid && !rx_take) begin
        overrun <= 1'b1;
        any_err <= 1'b1;
      end

      // results can land while settling; latch them for the reply
      if (decode_err)  seen_decode_err  <= 1'b1;
      if (book_err)    seen_book_err    <= 1'b1;
      if (book_update) seen_book_update <= 1'b1;
      if (decode_err || book_err) any_err <= 1'b1;

      case (state)
        ST_LEN_HI: if (rx_valid) begin
          len_hi           <= rx_byte;
          seen_decode_err  <= 1'b0;
          seen_book_err    <= 1'b0;
          seen_book_update <= 1'b0;
          state            <= ST_LEN_LO;
        end

        ST_LEN_LO: if (rx_valid) begin
          frame_len  <= {len_hi, rx_byte};
          byte_cnt   <= '0;
          settle_cnt <= '0;
          // a zero length frame has no body, itch_decode flags it at once
          state      <= ({len_hi, rx_byte} == 16'd0) ? ST_SETTLE : ST_BODY;
        end

        ST_BODY: if (rx_valid) begin
          if (byte_cnt == frame_len - 16'd1) begin
            settle_cnt <= '0;
            state      <= ST_SETTLE;
          end else begin
            byte_cnt <= byte_cnt + 16'd1;
          end
        end

        ST_SETTLE: begin
          if (settle_cnt == SETTLE_W'(SETTLE)) begin
            reply <= {
              2'b10, overrun, ask_valid, bid_valid,
              seen_book_update | book_update,
              seen_book_err | book_err,
              seen_decode_err | decode_err,
              bid_price, bid_qty, ask_price, ask_qty
            };
            tx_idx      <= '0;
            reply_start <= 1'b1;
            state       <= ST_SEND;
          end else begin
            settle_cnt <= settle_cnt + 1'b1;
          end
        end

        ST_SEND: if (tx_ready) begin
          reply <= {reply[8*REPLY_BYTES-9:0], 8'h00};
          if (tx_idx == 5'(REPLY_BYTES - 1)) state <= ST_LEN_HI;
          else tx_idx <= tx_idx + 5'd1;
        end

        default: state <= ST_LEN_HI;
      endcase
    end
  end

endmodule

`default_nettype wire
