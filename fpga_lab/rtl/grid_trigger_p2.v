// Grid trigger, two-stage pipeline. Same ports and rules as grid_trigger.v.
//
//   stage A  comparators (close vs every level)      -> register the bits
//   stage B  decisions on the slot state             -> register results/state
//
// The comparators do not touch the slot state, so cutting after them costs
// no throughput: while candle k+1 is being compared, candle k is deciding,
// and k+1 reaches stage B exactly when k's new state is in the registers.
// Latency 2 cycles, a new candle every cycle (in_ready is always 1).
module grid_trigger_p2 #(
    parameter N = 20,
    parameter W = 40,
    parameter PREFIX = 1        // budget selector in grid_decide.v
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
    reg  [W*(N+1)-1:0] levels;
    wire [N-1:0] ge_next, le, sell, buy, held_next, armed_next;

    // stage A -> B registers
    reg          a_valid;
    reg  [N-1:0] a_ge_next, a_le;
    reg  [5:0]   a_budget;

    assign in_ready = 1'b1;

    grid_compare #(.N(N), .W(W)) compare (
        .close(close), .levels(levels), .ge_next(ge_next), .le(le));
    grid_decide #(.N(N), .PREFIX(PREFIX)) decide (
        .held(held), .armed(armed), .ge_next(a_ge_next), .le(a_le), .budget(a_budget),
        .sell(sell), .buy(buy), .held_next(held_next), .armed_next(armed_next));

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
        if (rst) begin
            a_valid   <= 1'b0;
            out_valid <= 1'b0;
            sell_mask <= {N{1'b0}};
            buy_mask  <= {N{1'b0}};
            held      <= {N{1'b0}};
            armed     <= {N{1'b0}};
        end else begin
            a_valid   <= candle_valid;
            out_valid <= a_valid;
            if (state_we) begin
                held  <= state_held;
                armed <= state_armed;
            end else if (a_valid) begin
                sell_mask <= sell;
                buy_mask  <= buy;
                held      <= held_next;
                armed     <= armed_next;
            end
        end
    end
endmodule
