module accel_core
#(
    parameter integer N = 8,
    parameter integer K_max = 1024
)
(
    input clk,
    input rst,
    input [$clog2(K_max+1)-1:0] K,
    input in_valid,
    input out_ready,
    input start,
    input signed [N*8-1:0] a_in_TOP,
    input signed [N*8-1:0] b_in_TOP,
    output signed [N*32-1:0] res_out_TOP,
    output out_valid,
    output in_ready,
    output busy,
    output done
);

localparam [N*8-1:0] zero_beat = 0;

//a_in_TOP->[ZERO MUX]->a_in_zeroed->[SKEW]->a_in_skewed, same for B. 
wire signed [N*8-1:0] a_in_zeroed;
wire signed [N*8-1:0] a_in_skewed;
wire signed [N*8-1:0] b_in_zeroed;
wire signed [N*8-1:0] b_in_skewed;
wire zero_feed;
wire drain;
wire en;


assign a_in_zeroed = (zero_feed) ? zero_beat : a_in_TOP;
assign b_in_zeroed = (zero_feed) ? zero_beat : b_in_TOP; 

controller #(.N(N),
.K_max(K_max)) controller_instance
(
    .clk(clk),
    .rst(rst),
    .K(K),
    .in_valid(in_valid),
    .out_ready(out_ready),
    .start(start),
    .zero_feed(zero_feed),
    .out_valid(out_valid),
    .in_ready(in_ready),
    .en(en),
    .drain(drain),
    .busy(busy),
    .done(done)
);

skew #(.N(N)) skew_instance
(
    .clk(clk),
    .rst(rst),
    .en(en),
    .a_in(a_in_zeroed),
    .a_out(a_in_skewed),
    .b_in(b_in_zeroed),
    .b_out(b_in_skewed)
);

systolic_array #(.N(N)) array_instance
(
    .clk(clk),
    .rst(rst),
    .en(en),
    .drain(drain),
    .a(a_in_skewed),
    .b(b_in_skewed),
    .res_out(res_out_TOP)
);

endmodule