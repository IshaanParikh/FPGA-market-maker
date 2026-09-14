`default_nettype none

// OUCH 5.0 encoder for the three order-entry messages a market maker
// actually sends: Enter Order (O), Replace Order (U), Cancel Order (X).
// This is the reverse of itch_decode: one request comes in as a single
// pulse (every field arrives together, not byte by byte, so there is no
// need for a multi cycle gather phase), and the matching wire bytes go
// out one at a time, framed the same way as everywhere else in this
// project, a 2 byte big-endian length followed by the message body.
//
// Only the fixed, required part of each message is built here. OUCH 5.0
// also allows an optional trailing block of extra settings (minimum
// quantity, discretionary price, and so on), which this does not
// implement, so every message goes out with that block present but
// empty, which is a fully valid, spec legal message using OUCH's
// defaults for everything left unset.
//
// A request is only accepted while req_ready is high (the encoder is not
// already sending a previous one). Unlike itch_decode, an unsupported
// message type can never lead to a body length of zero: the length for
// this module always comes from its own lookup table for a type it just
// checked is valid, never from untrusted input, so that edge case does
// not apply here the way it did there.

module ouch_encode (
    input  logic clk,
    input  logic rst,

    input  logic       req_valid,
    output logic       req_ready,
    input  logic [7:0] msg_type,  // 'O', 'U', or 'X'

    input  logic [31:0]  user_ref_num,
    input  logic [31:0]  orig_user_ref_num,
    input  logic [7:0]   side,
    input  logic [31:0]  quantity,
    input  logic [63:0]  symbol,
    input  logic [63:0]  price,
    input  logic [7:0]   time_in_force,
    input  logic [7:0]   display,
    input  logic [7:0]   capacity,
    input  logic [7:0]   iso_eligible,
    input  logic [7:0]   cross_type,
    input  logic [111:0] clordid,

    output logic       data_valid,
    output logic [7:0] data_out,
    output logic       err_valid
);

  localparam int MAX_BODY_BYTES = 47;  // widest supported message: Enter Order, 47 bytes

  typedef enum logic [1:0] {
    ST_IDLE,
    ST_LEN_HI,
    ST_LEN_LO,
    ST_BODY
  } state_e;

  state_e      state;
  logic [15:0] body_len;
  logic [15:0] byte_cnt;
  logic [7:0]  body_q [0:MAX_BODY_BYTES-1];

  assign req_ready = (state == ST_IDLE);

  always_ff @(posedge clk) begin
    data_valid <= 1'b0;
    err_valid  <= 1'b0;

    if (rst) begin
      state <= ST_IDLE;
    end else begin
      case (state)
        // every field for this request is already on the inputs at once,
        // so the whole body can be laid out in a single cycle here
        ST_IDLE: if (req_valid) begin
          case (msg_type)
            "O": begin
              body_len <= 16'd47;
              body_q[0] <= "O";
              {body_q[1], body_q[2], body_q[3], body_q[4]} <= user_ref_num;
              body_q[5] <= side;
              {body_q[6], body_q[7], body_q[8], body_q[9]} <= quantity;
              {body_q[10], body_q[11], body_q[12], body_q[13],
               body_q[14], body_q[15], body_q[16], body_q[17]} <= symbol;
              {body_q[18], body_q[19], body_q[20], body_q[21],
               body_q[22], body_q[23], body_q[24], body_q[25]} <= price;
              body_q[26] <= time_in_force;
              body_q[27] <= display;
              body_q[28] <= capacity;
              body_q[29] <= iso_eligible;
              body_q[30] <= cross_type;
              {body_q[31], body_q[32], body_q[33], body_q[34], body_q[35], body_q[36], body_q[37],
               body_q[38], body_q[39], body_q[40], body_q[41], body_q[42], body_q[43], body_q[44]} <= clordid;
              {body_q[45], body_q[46]} <= 16'd0;  // Appendage Length: no optional appendage
              state <= ST_LEN_HI;
            end

            "U": begin
              body_len <= 16'd40;
              body_q[0] <= "U";
              {body_q[1], body_q[2], body_q[3], body_q[4]} <= orig_user_ref_num;
              {body_q[5], body_q[6], body_q[7], body_q[8]} <= user_ref_num;
              {body_q[9], body_q[10], body_q[11], body_q[12]} <= quantity;
              {body_q[13], body_q[14], body_q[15], body_q[16],
               body_q[17], body_q[18], body_q[19], body_q[20]} <= price;
              body_q[21] <= time_in_force;
              body_q[22] <= display;
              body_q[23] <= iso_eligible;
              {body_q[24], body_q[25], body_q[26], body_q[27], body_q[28], body_q[29], body_q[30],
               body_q[31], body_q[32], body_q[33], body_q[34], body_q[35], body_q[36], body_q[37]} <= clordid;
              {body_q[38], body_q[39]} <= 16'd0;
              state <= ST_LEN_HI;
            end

            "X": begin
              body_len <= 16'd11;
              body_q[0] <= "X";
              {body_q[1], body_q[2], body_q[3], body_q[4]} <= user_ref_num;
              {body_q[5], body_q[6], body_q[7], body_q[8]} <= quantity;
              {body_q[9], body_q[10]} <= 16'd0;
              state <= ST_LEN_HI;
            end

            default: err_valid <= 1'b1;  // not a message this module sends, nothing queued
          endcase
        end

        ST_LEN_HI: begin
          data_out   <= body_len[15:8];
          data_valid <= 1'b1;
          state      <= ST_LEN_LO;
        end

        ST_LEN_LO: begin
          data_out   <= body_len[7:0];
          data_valid <= 1'b1;
          byte_cnt   <= '0;
          state      <= ST_BODY;
        end

        ST_BODY: begin
          data_out   <= body_q[byte_cnt[5:0]];
          data_valid <= 1'b1;
          if (byte_cnt == body_len - 16'd1) state <= ST_IDLE;
          else byte_cnt <= byte_cnt + 16'd1;
        end

        default: state <= ST_IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire
