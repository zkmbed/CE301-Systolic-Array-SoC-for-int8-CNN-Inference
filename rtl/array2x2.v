module array2x2 (
input signed [7:0] a_in1,
input signed [7:0] a_in2,
input signed [7:0] b_in1,
input signed [7:0] b_in2,
input clk,
input en,
input rst,
input drain,
output wire signed [31:0] res_out1,
output wire signed [31:0] res_out2
);

wire signed [7:0] a_11_12;
wire signed [7:0] a_21_22;
wire signed [7:0] b_11_21;
wire signed [7:0] b_12_22;
wire signed [31:0] acc_11_21;
wire signed [31:0] acc_12_22;
wire signed [31:0] zero;
assign zero = {32{1'b0}};

mac_pe pe11 (

.clk(clk), 
.en(en), 
.rst(rst), 
.drain(drain), 
.a_in(a_in1), 
.b_in(b_in1),
.acc_in(zero),
.a_out(a_11_12),
.b_out(b_11_21),
.acc(acc_11_21)
);

mac_pe pe12 (

.clk(clk), 
.en(en), 
.rst(rst), 
.drain(drain), 
.a_in(a_11_12), 
.b_in(b_in2),
.acc_in(zero),
.b_out(b_12_22),
.acc(acc_12_22)
);
mac_pe pe21 (

.clk(clk), 
.en(en), 
.rst(rst), 
.drain(drain), 
.a_in(a_in2), 
.b_in(b_11_21),
.acc_in(acc_11_21),
.a_out(a_21_22),
.acc(res_out1)
);
mac_pe pe22 (

.clk(clk), 
.en(en), 
.rst(rst), 
.drain(drain), 
.a_in(a_21_22), 
.b_in(b_12_22),
.acc_in(acc_12_22),
.acc(res_out2)
);




endmodule