// Slot decisions for one candle, given the comparator bits. Mirrors the
// order of advance_demo_grid: sells first, then buys (lowest slot first,
// up to `budget`), then re-arm empty slots the price is back above.
//
// This logic reads the slot state and produces the next slot state, so in a
// pipeline it sits on the state feedback loop: it must finish in one cycle
// if a new candle is to enter every cycle.
//
// PREFIX selects how the budget is handed out (same result either way):
//   0  serial: a running count walks slots 0..N-1, so slot i waits on every
//      slot below it — N adders + compares in a row. On ECP5 this chain was
//      ~94 of the ~98 ns critical path of the single-stage design.
//   1  parallel prefix (grid_prefix_count.v): count the candidates below
//      every slot in log2(N) levels of small adders, then buy slot i iff
//      that count is under the budget. (Buys below i = min(candidates below i, budget), so
//      "buys below < budget" equals "candidates below < budget".)
module grid_decide #(
    parameter N = 20,
    parameter PREFIX = 1
) (
    input  wire [N-1:0] held,
    input  wire [N-1:0] armed,
    input  wire [N-1:0] ge_next,
    input  wire [N-1:0] le,
    input  wire [5:0]   budget,
    output reg  [N-1:0] sell,
    output reg  [N-1:0] buy,
    output reg  [N-1:0] held_next,
    output reg  [N-1:0] armed_next
);
    localparam CW = 6;  // count width: enough for N <= 63

    reg [N-1:0] kept, cand;
    always @* begin
        sell = held & ge_next;
        kept = held & ~sell;
        cand = armed & ~kept & le;
    end

    generate
        if (PREFIX == 0) begin : serial
            reg [5:0] used;
            integer i;
            always @* begin
                used = 6'd0;
                buy  = {N{1'b0}};
                for (i = 0; i < N; i = i + 1)
                    if (cand[i] && (used < budget)) begin
                        buy[i] = 1'b1;
                        used   = used + 6'd1;
                    end
            end
        end else begin : prefix
            wire [CW*N-1:0] below;
            integer i;
            grid_prefix_count #(.N(N), .CW(CW)) counter (.cand(cand), .below(below));
            always @*
                for (i = 0; i < N; i = i + 1)
                    buy[i] = cand[i] && (below[CW * i +: CW] < budget);
        end
    endgenerate

    always @* begin
        held_next  = kept | buy;
        armed_next = (armed & ~buy) | (~held_next & ~le);
    end
endmodule
