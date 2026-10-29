module skew #(
parameter integer N=8
)
(
    input clk,
    input en,
    input rst,
    input signed [N*8-1:0] a_in,
    input signed [N*8-1:0] b_in,
    output signed [N*8-1:0] a_out,
    output signed [N*8-1:0] b_out
);

reg[7:0] delay_a [0:N-1][0:N-1];
reg[7:0] delay_b [0:N-1][0:N-1];

integer i,j;

always @(posedge clk) begin
    if (rst) begin
        for (i=0; i<N; i=i+1) begin
            for (j=0; j<N; j=j+1) begin
                delay_a[i][j] <= 8'd0;
                delay_b[i][j] <= 8'd0;
            end
        end
    end
    else if(en) begin
        for (i=0; i<N; i=i+1) begin
            delay_a[i][0] <= a_in[(i*8) +: 8];
            delay_b[i][0] <= b_in[(i*8) +: 8];
        for (j=1; j<N; j=j+1) begin
            delay_a[i][j] <= delay_a[i][j-1];
            delay_b[i][j] <= delay_b[i][j-1];
        end
        end
    end
end

genvar k;
generate
    for (k=0; k<N; k=k+1) begin : output_assign
    if(k==0) begin : lane_0
        assign a_out[(k*8) +: 8]=a_in[(k*8) +: 8];
        assign b_out[(k*8) +: 8]=b_in[(k*8) +: 8];
    end
    else begin : lane_k
        assign a_out[(k*8) +: 8]=delay_a[k][k-1];
        assign b_out[(k*8) +: 8]=delay_b[k][k-1];
    end
    end
endgenerate
endmodule 

