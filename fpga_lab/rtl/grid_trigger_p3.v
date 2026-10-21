// Grid trigger, three stages, with the state loop itself cut in two.
// Same ports and rules as grid_trigger.v; always uses the prefix selector
// (PREFIX is accepted only so every variant has the same parameters).
//
//   stage A  comparators                                  -> register bits
//   stage B  read slot state: sells, candidates, prefix   -> register
//            counts of candidates below each slot
//   stage C  buy = candidate and count < budget; write    -> register results
//            the new slot state                              and state
//
// Stage B reads the slot state and stage C writes it, so the next candle
// may not reach stage B until this one has left stage C: one candle every
// 2 cycles (in_ready drops for the cycle after each accepted candle).
// Shorter stages allow a faster clock, but latency is 3 cycles and
// throughput is half a candle per cycle — the price of cutting a feedback
// loop rather than a feed-forward path.
module grid_trigger_p3 #(
    parameter N = 20,
    parameter W = 40,
    parameter PREFIX = 1
) (
    input  wire          clk,
    input  wire          rst,
    input  wire          level_we,
    input  wire [5:0]    level_addr,
    input  wire [W-1:0]  level_data,
    input  wire          state_we,
    input  wire [N-1:0]  state_held,
    input  wire [N-1:0]  state_armed,
    output wire          in_ready,
    input  wire          candle_valid,
    input  wire [W-1:0]  close,
    input  wire [5:0]    budget,
    output reg           out_valid,
    output reg  [N-1:0]  sell_mask,
    output reg  [N-1:0]  buy_mask,
    output reg  [N-1:0]  held,
    output reg  [N-1:0]  armed
);
    localparam CW = 6;

    reg  [W*(N+1)-1:0] levels;
    wire [N-1:0] ge_next, le;

    // stage A -> B
    reg          a_valid;
    reg  [N-1:0] a_ge_next, a_le;
    reg  [5:0]   a_budget;

    // stage B (combinational) and B -> C registers
    wire [N-1:0]    sell = held & a_ge_next;
    wire [N-1:0]    kept = held & ~sell;
    wire [N-1:0]    cand = armed & ~kept & a_le;
    wire [CW*N-1:0] below;
    reg             b_valid;
    reg  [N-1:0]    b_sell, b_kept, b_cand, b_le;
    reg  [CW*N-1:0] b_below;
    reg  [5:0]      b_budget;

    // stage C (combinational)
    reg  [N-1:0] buy, held_next, armed_next;
    integer i;

    assign in_ready = ~a_valid;

    grid_compare #(.N(N), .W(W)) compare (
        .close(close), .levels(levels), .ge_next(ge_next), .le(le));
    grid_prefix_count #(.N(N), .CW(CW)) counter (.cand(cand), .below(below));

    always @* begin
        for (i = 0; i < N; i = i + 1)
            buy[i] = b_cand[i] && (b_below[CW * i +: CW] < b_budget);
        held_next = b_kept | buy;
        // `armed` is still this candle's state: nothing else touches it
        // while the candle is in stage C.
        armed_next = (armed & ~buy) | (~held_next & ~b_le);
    end

    // Configuration write, one enable per level. (Written as
    // levels[W * level_addr +: W] it synthesized a hardware multiplier and a
    // wide shifter, and that path - used once at start-up - set the clock
    // limit of the whole chip.)
    genvar g;
    generate
        for (g = 0; g <= N; g = g + 1) begin : level_write
            always @(posedge clk)
                if (level_we && level_addr == g)
                    levels[W * g +: W] <= level_data;
        end
    endgenerate

    always @(posedge clk) begin
        a_ge_next <= ge_next;
        a_le      <= le;
        a_budget  <= budget;
        b_sell    <= sell;
        b_kept    <= kept;
        b_cand    <= cand;
        b_le      <= a_le;
        b_below   <= below;
        b_budget  <= a_budget;
        if (rst) begin
            a_valid   <= 1'b0;
            b_valid   <= 1'b0;
            out_valid <= 1'b0;
            sell_mask <= {N{1'b0}};
            buy_mask  <= {N{1'b0}};
            held      <= {N{1'b0}};
            armed     <= {N{1'b0}};
        end else begin
            a_valid   <= candle_valid && in_ready;
            b_valid   <= a_valid;
            out_valid <= b_valid;
            if (state_we) begin
                held  <= state_held;
                armed <= state_armed;
            end else if (b_valid) begin
                sell_mask <= b_sell;
                buy_mask  <= buy;
                held      <= held_next;
                armed     <= armed_next;
            end
        end
    end
endmodule
