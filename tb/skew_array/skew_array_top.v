// Test-only wrapper: skew feeding systolic_array. Not part of the design.
module skew_array_top #(parameter N = 4) (
    input clk, input en, input rst, input drain,
    input  signed [N*8-1:0]  a,
    input  signed [N*8-1:0]  b,
    output signed [N*32-1:0] res_out
);
    wire signed [N*8-1:0] a_skewed, b_skewed;
    skew #(.N(N)) u_skew (.clk(clk), .en(en), .rst(rst),
                          .a_in(a), .b_in(b), .a_out(a_skewed), .b_out(b_skewed));
    systolic_array #(.N(N)) u_array (.clk(clk), .en(en), .rst(rst), .drain(drain),
                                     .a(a_skewed), .b(b_skewed), .res_out(res_out));
endmodule
