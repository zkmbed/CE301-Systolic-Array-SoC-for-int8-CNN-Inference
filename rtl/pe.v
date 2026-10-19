module mac_pe (input clk, 
input rst, 
input en, 
input drain,
input signed [31:0] acc_in,
input signed [7:0] a_in, 
input signed [7:0] b_in, 
output reg signed [7:0] a_out, 
output reg signed [7:0] b_out,
output reg signed [31:0] acc);


always @(posedge clk) begin
    if (rst) begin
    acc <= 0;
    a_out <= 0;
    b_out <= 0;
    end
    else if(~(drain)) begin
    if (en) begin
    a_out <= a_in;
    b_out <= b_in;
    acc <= acc + a_in * b_in;
    end 
end
else begin
    if(en) begin
        acc <= acc_in;
end
end
end
endmodule 
