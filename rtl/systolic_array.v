module systolic_array
#(
parameter N = 8
)
(
input clk,
input en,
input rst,
input drain,
input signed [N*8-1:0] a,
input signed [N*8-1:0] b,
output signed [N*32-1:0] res_out
);


wire signed [7:0] horizontal [0:N-1][0:N];
wire signed [7:0] vertical [0:N][0:N-1];
wire signed [31:0] acc_bus [0:N][0:N-1];

genvar i,j,k;
generate 
    for(k=0; k<N; k=k+1) begin : edge_loop
    assign horizontal[k][0]=a[(k*8)+:8];
    assign vertical[0][k]=b[(k*8)+:8];
    assign acc_bus[0][k]=0;
    assign res_out[(k*32)+:32]=acc_bus[N][k];
    end
    for (i=0; i<N; i=i+1) begin : row_loop
        for (j=0; j<N; j=j+1) begin : col_loop
        
            mac_pe pe(
                .clk(clk),
                .en(en), 
                .rst(rst), 
                .drain(drain), 
                .a_in(horizontal[i][j]), 
                .b_in(vertical[i][j]),
                .acc_in(acc_bus[i][j]),
                .a_out(horizontal[i][j+1]),
                .b_out(vertical[i+1][j]),
                .acc(acc_bus[i+1][j])
);
        end
    end
endgenerate
endmodule

