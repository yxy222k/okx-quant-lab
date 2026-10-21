// For every slot i: how many candidate slots lie below it (0..i-1).
// Kogge-Stone parallel prefix: log2(N) levels of small adders, so slot 19
// waits on 5 adder delays instead of 19 in a row.
module grid_prefix_count #(
    parameter N = 20,
    parameter CW = 6            // count width: enough for N <= 63
) (
    input  wire [N-1:0]      cand,
    output reg  [CW*N-1:0]   below      // slot i's count at [CW*i +: CW]
);
    reg [CW*N-1:0] count, next;         // count[i]: candidates in 0..i
    integer i, step;

    always @* begin
        for (i = 0; i < N; i = i + 1)
            count[CW * i +: CW] = {{(CW - 1){1'b0}}, cand[i]};
        for (step = 1; step < N; step = step * 2) begin
            next = count;
            for (i = step; i < N; i = i + 1)
                next[CW * i +: CW] = count[CW * i +: CW] + count[CW * (i - step) +: CW];
            count = next;
        end
        below[CW * 0 +: CW] = {CW{1'b0}};
        for (i = 1; i < N; i = i + 1)
            below[CW * i +: CW] = count[CW * (i - 1) +: CW];
    end
endmodule
