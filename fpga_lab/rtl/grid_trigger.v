// Close-confirmed grid trigger, single stage: one candle in, buy/sell slot
// masks out on the next clock edge.
//
// Hardware twin of the per-candle rules in src/okx_quant_lab/demo_grid.py
// (advance_demo_grid):
//   sell  slot i  if it holds and close >= level[i+1]
//   buy   slot i  if armed, empty, close <= level[i], and budget remains
//                 (lowest slots first, as the Python loop runs i = 0..N-1)
//   re-arm slot i if empty, not armed, and close > level[i]
// What needs exchange fills stays in software: the host passes `budget`,
// the number of slot_cash buys the cash affords after this candle's sells;
// the daily-loss breaker and sub-lot dust handling are not modelled.
//
// All logic (comparators + decisions) sits between two clock edges:
// latency 1 cycle, a new candle every cycle (in_ready is always 1). The
// pipelined variants (grid_trigger_p*.v) share the same ports and logic.
module grid_trigger #(
    parameter N = 20,           // slots; levels are indexed 0..N
    parameter W = 40,           // fixed-point price width
    parameter PREFIX = 1        // budget selector in grid_decide.v
) (
    input  wire          clk,
    input  wire          rst,
    // configuration: write one level, or load the slot state
    input  wire          level_we,
    input  wire [5:0]    level_addr,
    input  wire [W-1:0]  level_data,
    input  wire          state_we,
    input  wire [N-1:0]  state_held,
    input  wire [N-1:0]  state_armed,
    // one candle
    output wire          in_ready,
    input  wire          candle_valid,
    input  wire [W-1:0]  close,
    input  wire [5:0]    budget,
    // results
    output reg           out_valid,
    output reg  [N-1:0]  sell_mask,
    output reg  [N-1:0]  buy_mask,
    output reg  [N-1:0]  held,
    output reg  [N-1:0]  armed
);
    reg  [W*(N+1)-1:0] levels;
    wire [N-1:0] ge_next, le, sell, buy, held_next, armed_next;

    assign in_ready = 1'b1;

    grid_compare #(.N(N), .W(W)) compare (
        .close(close), .levels(levels), .ge_next(ge_next), .le(le));
    grid_decide #(.N(N), .PREFIX(PREFIX)) decide (
        .held(held), .armed(armed), .ge_next(ge_next), .le(le), .budget(budget),
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
        if (rst) begin
            out_valid <= 1'b0;
            sell_mask <= {N{1'b0}};
            buy_mask  <= {N{1'b0}};
            held      <= {N{1'b0}};
            armed     <= {N{1'b0}};
        end else begin
            out_valid <= candle_valid;
            if (state_we) begin
                held  <= state_held;
                armed <= state_armed;
            end else if (candle_valid) begin
                sell_mask <= sell;
                buy_mask  <= buy;
                held      <= held_next;
                armed     <= armed_next;
            end
        end
    end
endmodule
