// Price comparators for one candle: the only part of the grid rules that
// looks at prices. Pure combinational and stateless, so it can be pipelined
// freely. Every comparator is W bits wide and all 2*N run in parallel.
module grid_compare #(
    parameter N = 20,
    parameter W = 40
) (
    input  wire [W-1:0]         close,
    input  wire [W*(N+1)-1:0]   levels,     // level i at [W*i +: W]
    output wire [N-1:0]         ge_next,    // close >= level[i+1]: slot i may sell
    output wire [N-1:0]         le          // close <= level[i]:   slot i may buy
);                                          // (~le is close > level[i]: re-arm)
    genvar i;
    generate
        for (i = 0; i < N; i = i + 1) begin : cmp
            assign ge_next[i] = close >= levels[W * (i + 1) +: W];
            assign le[i]      = close <= levels[W * i +: W];
        end
    endgenerate
endmodule
