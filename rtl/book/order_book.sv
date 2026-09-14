`default_nettype none

// A simple order book for one stock. It keeps track of every order that
// is currently resting (not yet filled or cancelled), and reports the
// best price a buyer is willing to pay (the bid) and the best price a
// seller is willing to accept (the ask), along with how many shares are
// available at each.
//
// Orders live in a small table, spread across a few parallel arrays
// (one entry per order, matched up by index) instead of one array of
// records. An order's ID number does not tell you where it lives in the
// table, so finding it means checking every entry, the same way you
// would scan a short list by hand.
//
// The best bid and ask are recomputed from the whole table after every
// message instead of being tracked incrementally. That is simpler to
// reason about and easier to check against a reference model, at the
// cost of redoing work that did not need to change.

module order_book #(
    parameter int CAPACITY = 64
) (
    input  logic        clk,
    input  logic        rst,

    // one decoded ITCH message per pulse, in the same format itch_decode
    // produces
    input  logic        msg_valid,
    input  logic [7:0]  msg_type,
    input  logic [63:0] order_ref,
    input  logic [7:0]  side,
    input  logic [31:0] shares,
    input  logic [31:0] price,
    input  logic [31:0] executed_shares,
    input  logic [31:0] cancelled_shares,
    input  logic [63:0] original_order_ref,
    input  logic [63:0] new_order_ref,

    // exactly one of these pulses one cycle after msg_valid, once the
    // message has been applied (or rejected)
    output logic        update_valid,
    output logic        err_valid,

    // the current best bid and ask, held steady until the next update
    output logic        bid_valid,
    output logic [31:0] bid_price,
    output logic [31:0] bid_qty,

    output logic        ask_valid,
    output logic [31:0] ask_price,
    output logic [31:0] ask_qty
);

  localparam int IDX_WIDTH = $clog2(CAPACITY);
  localparam logic [7:0] SIDE_BUY  = "B";
  localparam logic [7:0] SIDE_SELL = "S";

  // the order table
  logic        valid_q     [0:CAPACITY-1];
  logic [7:0]  side_q      [0:CAPACITY-1];
  logic [31:0] price_q     [0:CAPACITY-1];
  logic [31:0] shares_q    [0:CAPACITY-1];
  logic [63:0] order_ref_q [0:CAPACITY-1];

  // a replace names the order being replaced, everything else names
  // itself
  logic [63:0] lookup_ref;
  assign lookup_ref = (msg_type == "U") ? original_order_ref : order_ref;

  // find the order this message refers to, if it exists
  logic                 match_found;
  logic [IDX_WIDTH-1:0] match_index;
  always_comb begin
    match_found = 1'b0;
    match_index = '0;
    for (int i = 0; i < CAPACITY; i++) begin
      if (!match_found && valid_q[i] && order_ref_q[i] == lookup_ref) begin
        match_found = 1'b1;
        match_index = i[IDX_WIDTH-1:0];
      end
    end
  end

  // find an empty slot for a new order, if one exists
  logic                 free_found;
  logic [IDX_WIDTH-1:0] free_index;
  always_comb begin
    free_found = 1'b0;
    free_index = '0;
    for (int i = 0; i < CAPACITY; i++) begin
      if (!free_found && !valid_q[i]) begin
        free_found = 1'b1;
        free_index = i[IDX_WIDTH-1:0];
      end
    end
  end

  // decode the message type into one control signal per operation,
  // the same way an opcode gets decoded into control signals
  logic is_add, is_exec, is_cancel, is_delete, is_replace, known_type;
  assign is_add     = msg_valid && (msg_type == "A" || msg_type == "F");
  assign is_exec    = msg_valid && (msg_type == "E" || msg_type == "C");
  assign is_cancel  = msg_valid && (msg_type == "X");
  assign is_delete  = msg_valid && (msg_type == "D");
  assign is_replace = msg_valid && (msg_type == "U");
  assign known_type = is_add || is_exec || is_cancel || is_delete || is_replace;

  // shrinking an order can never take it below zero shares; treat an
  // amount larger than what is left as using up all of it
  logic [31:0] shares_after_exec, shares_after_cancel;
  assign shares_after_exec   = (shares_q[match_index] > executed_shares)
                              ? (shares_q[match_index] - executed_shares) : 32'd0;
  assign shares_after_cancel = (shares_q[match_index] > cancelled_shares)
                              ? (shares_q[match_index] - cancelled_shares) : 32'd0;

  logic remove_after_exec, remove_after_cancel;
  assign remove_after_exec   = is_exec   && (shares_after_exec   == 32'd0);
  assign remove_after_cancel = is_cancel && (shares_after_cancel == 32'd0);

  // a message succeeds only if the order it names actually exists (or,
  // for a new order, if there is room for it)
  logic next_err;
  assign next_err = (msg_valid   && !known_type)
                  || (is_add     && !free_found)
                  || (is_exec    && !match_found)
                  || (is_cancel  && !match_found)
                  || (is_delete  && !match_found)
                  || (is_replace && !match_found);

  // what the table will look like right after this message is applied,
  // used below to work out the new best bid/ask in the same cycle
  logic        next_valid     [0:CAPACITY-1];
  logic [7:0]  next_side      [0:CAPACITY-1];
  logic [31:0] next_price     [0:CAPACITY-1];
  logic [31:0] next_shares    [0:CAPACITY-1];
  logic [63:0] next_order_ref [0:CAPACITY-1];

  always_comb begin
    next_valid     = valid_q;
    next_side      = side_q;
    next_price     = price_q;
    next_shares    = shares_q;
    next_order_ref = order_ref_q;

    if (is_add && free_found) begin
      next_valid[free_index]     = 1'b1;
      next_side[free_index]      = side;
      next_price[free_index]     = price;
      next_shares[free_index]    = shares;
      next_order_ref[free_index] = order_ref;
    end

    if (is_exec && match_found) begin
      if (remove_after_exec) next_valid[match_index]  = 1'b0;
      else                   next_shares[match_index] = shares_after_exec;
    end

    if (is_cancel && match_found) begin
      if (remove_after_cancel) next_valid[match_index]  = 1'b0;
      else                     next_shares[match_index] = shares_after_cancel;
    end

    if (is_delete && match_found) begin
      next_valid[match_index] = 1'b0;
    end

    if (is_replace && match_found) begin
      // the side stays whatever it already was: a replace message never
      // says which side the order is on
      next_order_ref[match_index] = new_order_ref;
      next_price[match_index]     = price;
      next_shares[match_index]    = shares;
    end
  end

  // best bid: the highest price among buy orders, and the total shares
  // waiting at that price
  logic        next_bid_valid;
  logic [31:0] next_bid_price, next_bid_qty;
  always_comb begin
    next_bid_valid = 1'b0;
    next_bid_price = '0;
    for (int i = 0; i < CAPACITY; i++) begin
      if (next_valid[i] && next_side[i] == SIDE_BUY) begin
        if (!next_bid_valid || next_price[i] > next_bid_price) begin
          next_bid_valid = 1'b1;
          next_bid_price = next_price[i];
        end
      end
    end
  end
  always_comb begin
    next_bid_qty = '0;
    for (int i = 0; i < CAPACITY; i++) begin
      if (next_valid[i] && next_side[i] == SIDE_BUY && next_price[i] == next_bid_price) begin
        next_bid_qty = next_bid_qty + next_shares[i];
      end
    end
  end

  // best ask: the lowest price among sell orders, same idea
  logic        next_ask_valid;
  logic [31:0] next_ask_price, next_ask_qty;
  always_comb begin
    next_ask_valid = 1'b0;
    next_ask_price = '0;
    for (int i = 0; i < CAPACITY; i++) begin
      if (next_valid[i] && next_side[i] == SIDE_SELL) begin
        if (!next_ask_valid || next_price[i] < next_ask_price) begin
          next_ask_valid = 1'b1;
          next_ask_price = next_price[i];
        end
      end
    end
  end
  always_comb begin
    next_ask_qty = '0;
    for (int i = 0; i < CAPACITY; i++) begin
      if (next_valid[i] && next_side[i] == SIDE_SELL && next_price[i] == next_ask_price) begin
        next_ask_qty = next_ask_qty + next_shares[i];
      end
    end
  end

  // commit everything on the clock edge
  always_ff @(posedge clk) begin
    if (rst) begin
      for (int i = 0; i < CAPACITY; i++) valid_q[i] <= 1'b0;
      update_valid <= 1'b0;
      err_valid    <= 1'b0;
      bid_valid    <= 1'b0;
      bid_price    <= '0;
      bid_qty      <= '0;
      ask_valid    <= 1'b0;
      ask_price    <= '0;
      ask_qty      <= '0;
    end else begin
      valid_q     <= next_valid;
      side_q      <= next_side;
      price_q     <= next_price;
      shares_q    <= next_shares;
      order_ref_q <= next_order_ref;

      update_valid <= msg_valid && !next_err;
      err_valid    <= next_err;

      bid_valid <= next_bid_valid;
      bid_price <= next_bid_price;
      bid_qty   <= next_bid_qty;

      ask_valid <= next_ask_valid;
      ask_price <= next_ask_price;
      ask_qty   <= next_ask_qty;
    end
  end

endmodule

`default_nettype wire
