// Timing harness: registers every port of the design under test, so the
// reported Fmax is the design's own register-to-register speed rather than
// pin-to-register paths. The design is chosen at synthesis time with
// `read_verilog -DDUT=<module> -DPREFIX=<0|1>`; every variant has the
// same ports.
module harness #(
    parameter N = 20,
    parameter W = 40
) (
    input  wire          clk,
    input  wire          rst,
    input  wire          level_we,
    input  wire [5:0]    level_addr,
    input  wire [W-1:0]  level_data,
    input  wire          state_we,
    input  wire [N-1:0]  state_held,
    input  wire [N-1:0]  state_armed,
    output reg           in_ready,
    input  wire          candle_valid,
    input  wire [W-1:0]  close,
    input  wire [5:0]    budget,
    output reg           out_valid,
    output reg  [N-1:0]  sell_mask,
    output reg  [N-1:0]  buy_mask,
    output reg  [N-1:0]  held,
    output reg  [N-1:0]  armed
);
    reg          r_rst, r_level_we, r_state_we, r_candle_valid;
    reg  [5:0]   r_level_addr, r_budget;
    reg  [W-1:0] r_level_data, r_close;
    reg  [N-1:0] r_state_held, r_state_armed;
    wire         d_in_ready, d_out_valid;
    wire [N-1:0] d_sell_mask, d_buy_mask, d_held, d_armed;

    always @(posedge clk) begin
        r_rst          <= rst;
        r_level_we     <= level_we;
        r_level_addr   <= level_addr;
        r_level_data   <= level_data;
        r_state_we     <= state_we;
        r_state_held   <= state_held;
        r_state_armed  <= state_armed;
        r_candle_valid <= candle_valid;
        r_close        <= close;
        r_budget       <= budget;
        in_ready       <= d_in_ready;
        out_valid      <= d_out_valid;
        sell_mask      <= d_sell_mask;
        buy_mask       <= d_buy_mask;
        held           <= d_held;
        armed          <= d_armed;
    end

    `DUT #(.N(N), .W(W), .PREFIX(`PREFIX)) dut (
        .clk(clk), .rst(r_rst),
        .level_we(r_level_we), .level_addr(r_level_addr), .level_data(r_level_data),
        .state_we(r_state_we), .state_held(r_state_held), .state_armed(r_state_armed),
        .in_ready(d_in_ready), .candle_valid(r_candle_valid), .close(r_close),
        .budget(r_budget),
        .out_valid(d_out_valid), .sell_mask(d_sell_mask), .buy_mask(d_buy_mask),
        .held(d_held), .armed(d_armed));
endmodule
