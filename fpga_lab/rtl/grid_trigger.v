// Close-confirmed grid trigger: one candle in, buy/sell slot masks out.
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
// Prices are unsigned fixed point (the host picks the scale). Decisions are
// combinational and registered on the clock edge that samples candle_valid,
// so results appear one cycle later with out_valid.
module grid_trigger #(
    parameter N = 20,           // slots; levels are indexed 0..N
    parameter W = 40            // fixed-point price width
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
    reg [W-1:0] level [0:N];

    reg [N-1:0] sell_c, buy_c, held_c, armed_c;
    reg [5:0]   used;
    integer i;

    always @* begin
        // Sells first: a slot bought on this candle cannot sell on it.
        for (i = 0; i < N; i = i + 1)
            sell_c[i] = held[i] && (close >= level[i + 1]);
        held_c = held & ~sell_c;

        // Buys: a running count makes this a priority selector, so the
        // budget goes to the lowest qualifying slots.
        used  = 6'd0;
        buy_c = {N{1'b0}};
        for (i = 0; i < N; i = i + 1)
            if (armed[i] && !held_c[i] && (close <= level[i]) && (used < budget)) begin
                buy_c[i] = 1'b1;
                used     = used + 6'd1;
            end
        held_c  = held_c | buy_c;
        armed_c = armed & ~buy_c;

        // Re-arm empty slots the price has moved back above.
        for (i = 0; i < N; i = i + 1)
            if (!held_c[i] && !armed_c[i] && (close > level[i]))
                armed_c[i] = 1'b1;
    end

    always @(posedge clk) begin
        if (rst) begin
            out_valid <= 1'b0;
            sell_mask <= {N{1'b0}};
            buy_mask  <= {N{1'b0}};
            held      <= {N{1'b0}};
            armed     <= {N{1'b0}};
        end else begin
            out_valid <= candle_valid;
            if (level_we)
                level[level_addr] <= level_data;
            if (state_we) begin
                held  <= state_held;
                armed <= state_armed;
            end else if (candle_valid) begin
                sell_mask <= sell_c;
                buy_mask  <= buy_c;
                held      <= held_c;
                armed     <= armed_c;
            end
        end
    end
endmodule
