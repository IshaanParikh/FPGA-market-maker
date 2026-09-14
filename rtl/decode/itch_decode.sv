`default_nettype none

// ITCH 5.0 decoder, byte-serial input, same message subset and framing as
// model/itch.py: a 2 byte big-endian length prefix per message, then the
// message body. Order book types only (A, F, E, C, X, D, U). Anything else,
// or a length that does not match the decoded type, is flagged on err_valid
// instead of guessed at.
//
// Fields not used by the current message type keep their previous value.
// Only trust an output field on the same cycle msg_valid is high, and only
// the fields that message type actually carries.

module itch_decode (
    input  logic        clk,
    input  logic        rst,
    input  logic [7:0]  data_in,
    input  logic        valid_in,

    output logic        msg_valid,
    output logic        err_valid,
    output logic [7:0]  msg_type,

    output logic [15:0] stock_locate,
    output logic [15:0] tracking_number,
    output logic [47:0] timestamp,
    output logic [63:0] order_ref,
    output logic [7:0]  side,
    output logic [31:0] shares,
    output logic [63:0] stock,
    output logic [31:0] price,
    output logic [31:0] executed_shares,
    output logic [63:0] match_number,
    output logic [7:0]  printable,
    output logic [31:0] cancelled_shares,
    output logic [63:0] original_order_ref,
    output logic [63:0] new_order_ref,
    output logic [31:0] attribution
);

  localparam int MAX_BODY_BYTES = 40;  // widest supported message: F, 40 bytes

  typedef enum logic [1:0] {
    ST_LEN_HI,
    ST_LEN_LO,
    ST_BODY,
    ST_DECODE
  } state_e;

  state_e      state;
  logic [15:0] frame_len;
  logic [15:0] byte_cnt;
  logic [7:0]  body [0:MAX_BODY_BYTES-1];

  function automatic logic [5:0] expected_len(logic [7:0] mtype);
    case (mtype)
      "A": expected_len = 6'd36;
      "F": expected_len = 6'd40;
      "E": expected_len = 6'd31;
      "C": expected_len = 6'd36;
      "X": expected_len = 6'd23;
      "D": expected_len = 6'd19;
      "U": expected_len = 6'd35;
      default: expected_len = 6'd0;
    endcase
  endfunction

  logic [5:0] exp_len;
  assign exp_len = expected_len(body[0]);

  always_ff @(posedge clk) begin
    msg_valid <= 1'b0;
    err_valid <= 1'b0;

    if (rst) begin
      state    <= ST_LEN_HI;
      byte_cnt <= '0;
    end else begin
      case (state)
        ST_LEN_HI: if (valid_in) begin
          frame_len[15:8] <= data_in;
          state           <= ST_LEN_LO;
        end

        ST_LEN_LO: if (valid_in) begin
          frame_len[7:0] <= data_in;
          byte_cnt       <= '0;
          // a declared length of 0 has no body to read, decode right away
          state          <= ({frame_len[15:8], data_in} == 16'd0) ? ST_DECODE : ST_BODY;
        end

        ST_BODY: if (valid_in) begin
          if (byte_cnt < MAX_BODY_BYTES[15:0]) body[byte_cnt[5:0]] <= data_in;
          if (byte_cnt == frame_len - 16'd1) state <= ST_DECODE;
          else byte_cnt <= byte_cnt + 16'd1;
        end

        // one cycle after the last body byte, so `body` has settled before
        // it is read here: reading body[byte_cnt] the same cycle it is
        // written would return the pre-write value, not the new byte.
        ST_DECODE: begin
          msg_type <= body[0];
          if (exp_len != 6'd0 && frame_len == {10'd0, exp_len}) begin
            msg_valid       <= 1'b1;
            stock_locate    <= {body[1], body[2]};
            tracking_number <= {body[3], body[4]};
            timestamp       <= {body[5], body[6], body[7], body[8], body[9], body[10]};

            case (body[0])
              "A": begin
                order_ref <= {body[11], body[12], body[13], body[14], body[15], body[16], body[17], body[18]};
                side      <= body[19];
                shares    <= {body[20], body[21], body[22], body[23]};
                stock     <= {body[24], body[25], body[26], body[27], body[28], body[29], body[30], body[31]};
                price     <= {body[32], body[33], body[34], body[35]};
              end
              "F": begin
                order_ref   <= {body[11], body[12], body[13], body[14], body[15], body[16], body[17], body[18]};
                side        <= body[19];
                shares      <= {body[20], body[21], body[22], body[23]};
                stock       <= {body[24], body[25], body[26], body[27], body[28], body[29], body[30], body[31]};
                price       <= {body[32], body[33], body[34], body[35]};
                attribution <= {body[36], body[37], body[38], body[39]};
              end
              "E": begin
                order_ref       <= {body[11], body[12], body[13], body[14], body[15], body[16], body[17], body[18]};
                executed_shares <= {body[19], body[20], body[21], body[22]};
                match_number    <= {body[23], body[24], body[25], body[26], body[27], body[28], body[29], body[30]};
              end
              "C": begin
                order_ref       <= {body[11], body[12], body[13], body[14], body[15], body[16], body[17], body[18]};
                executed_shares <= {body[19], body[20], body[21], body[22]};
                match_number    <= {body[23], body[24], body[25], body[26], body[27], body[28], body[29], body[30]};
                printable       <= body[31];
                price           <= {body[32], body[33], body[34], body[35]};
              end
              "X": begin
                order_ref        <= {body[11], body[12], body[13], body[14], body[15], body[16], body[17], body[18]};
                cancelled_shares <= {body[19], body[20], body[21], body[22]};
              end
              "D": begin
                order_ref <= {body[11], body[12], body[13], body[14], body[15], body[16], body[17], body[18]};
              end
              "U": begin
                original_order_ref <= {body[11], body[12], body[13], body[14], body[15], body[16], body[17], body[18]};
                new_order_ref       <= {body[19], body[20], body[21], body[22], body[23], body[24], body[25], body[26]};
                shares              <= {body[27], body[28], body[29], body[30]};
                price               <= {body[31], body[32], body[33], body[34]};
              end
              default: ;  // unreachable: exp_len != 0 already limits body[0] to a known type
            endcase
          end else begin
            err_valid <= 1'b1;
          end
          state <= ST_LEN_HI;
        end

        default: state <= ST_LEN_HI;
      endcase
    end
  end

endmodule

`default_nettype wire
