module controller
#(
parameter integer N=8,
parameter integer K_max=1024
)
(
    input clk,
    input rst,
    input [$clog2(K_max+1)-1:0] K,
    input in_valid,
    input out_ready,
    input start,
    output zero_feed,
    output out_valid,
    output in_ready,
    output en,
    output drain,
    output busy,
    output done
);

localparam K_width = $clog2(K_max+1);
localparam IDLE = 0;
localparam COMPUTE = 1;
localparam FLUSH = 2;
localparam DRAIN = 3;
localparam DONE = 4;

localparam [31:0] FLUSH_LAST = (2*N-2)-1;
localparam [31:0] DRAIN_LAST = N-1;

reg [K_width-1:0] k_reg;
reg [K_width-1:0] count_reg;
reg [2:0] state_reg;
reg [2:0] next_state;

always @(posedge clk) begin
    if(rst) begin
        k_reg <= 0;
        state_reg <= IDLE;
        count_reg <= 0;
    end
    else begin
        state_reg <= next_state;
    
        if(state_reg == IDLE && next_state == COMPUTE)begin
        k_reg <= K;
        end
    
        if(next_state != state_reg) begin
        count_reg <= 0;
        end 
        else if(en == 1) begin
            count_reg <= count_reg + 1;
        end
    end
end

always @(*) begin
    next_state = state_reg;

    case (state_reg)

    IDLE : begin

        if(start) begin
            next_state = COMPUTE;
        end
    end

    COMPUTE : begin

        if((count_reg == k_reg - 1) && (in_valid && in_ready))begin
            next_state = FLUSH;
        end
    end

    FLUSH : begin
        if(count_reg == FLUSH_LAST[K_width-1:0]) begin
            next_state = DRAIN;
        end
    end

    DRAIN : begin
        if((count_reg == DRAIN_LAST[K_width-1:0]) && (out_valid && out_ready)) begin
            next_state = DONE;
        end
    end

    DONE : begin
        next_state = IDLE;
    end

    default : begin
        next_state = IDLE;
    end
    endcase
end

assign in_ready = (state_reg==COMPUTE);
assign out_valid = (state_reg==DRAIN);
assign zero_feed = ((state_reg==FLUSH) || (state_reg==DRAIN));
assign drain = (state_reg==DRAIN);
assign busy = ((state_reg==COMPUTE)||(state_reg==FLUSH)||(state_reg==DRAIN));
assign done = (state_reg==DONE);
assign en = ((state_reg==COMPUTE && in_valid)||(state_reg==FLUSH)||(state_reg==DRAIN && out_ready));

endmodule