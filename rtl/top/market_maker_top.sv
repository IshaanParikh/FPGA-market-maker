`default_nettype none

// Wires the ITCH decoder straight into the order book. Every field
// itch_decode produces lines up with what order_book expects, by design,
// so this module is mostly just connecting the two together.
//
// decode_err pulses when a byte stream could not be decoded at all (bad
// length, unknown message type). book_err pulses when a message decoded
// fine but could not be applied to the book (an unknown order, or the
// table is full). They are reported separately since they mean different
// things, and a message that fails to decode never reaches the book at
// all, so the two can never pulse together for the same message.

module market_maker_top #(
    parameter int CAPACITY = 64
) (
    input  logic       clk,
    input  logic       rst,

    input  logic [7:0] data_in,
    input  logic       valid_in,

    output logic       decode_err,

    output logic       book_update,
    output logic       book_err,

    output logic        bid_valid,
    output logic [31:0] bid_price,
    output logic [31:0] bid_qty,

    output logic        ask_valid,
    output logic [31:0] ask_price,
    output logic [31:0] ask_qty
);

  logic        msg_valid;
  logic [7:0]  msg_type;
  logic [63:0] order_ref;
  logic [7:0]  side;
  logic [31:0] shares;
  logic [31:0] price;
  logic [31:0] executed_shares;
  logic [31:0] cancelled_shares;
  logic [63:0] original_order_ref;
  logic [63:0] new_order_ref;

  // itch_decode also produces stock_locate, tracking_number, timestamp,
  // stock, match_number, printable, and attribution. Nothing downstream
  // needs them yet (this book tracks one instrument and does not report
  // trades), so they are left explicitly unconnected rather than wired
  // to signals nothing reads.
  /* verilator lint_off PINCONNECTEMPTY */
  itch_decode u_decode (
      .clk     (clk),
      .rst     (rst),
      .data_in (data_in),
      .valid_in(valid_in),

      .msg_valid(msg_valid),
      .err_valid(decode_err),
      .msg_type (msg_type),

      .stock_locate      (),
      .tracking_number   (),
      .timestamp         (),
      .order_ref         (order_ref),
      .side              (side),
      .shares            (shares),
      .stock             (),
      .price             (price),
      .executed_shares   (executed_shares),
      .match_number      (),
      .printable         (),
      .cancelled_shares  (cancelled_shares),
      .original_order_ref(original_order_ref),
      .new_order_ref     (new_order_ref),
      .attribution       ()
  );
  /* verilator lint_on PINCONNECTEMPTY */

  order_book #(
      .CAPACITY(CAPACITY)
  ) u_book (
      .clk(clk),
      .rst(rst),

      .msg_valid         (msg_valid),
      .msg_type          (msg_type),
      .order_ref         (order_ref),
      .side              (side),
      .shares            (shares),
      .price             (price),
      .executed_shares   (executed_shares),
      .cancelled_shares  (cancelled_shares),
      .original_order_ref(original_order_ref),
      .new_order_ref     (new_order_ref),

      .update_valid(book_update),
      .err_valid   (book_err),

      .bid_valid(bid_valid),
      .bid_price(bid_price),
      .bid_qty  (bid_qty),

      .ask_valid(ask_valid),
      .ask_price(ask_price),
      .ask_qty  (ask_qty)
  );

endmodule

`default_nettype wire
