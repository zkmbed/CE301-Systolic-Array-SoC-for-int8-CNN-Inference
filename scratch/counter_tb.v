module counter_tb;
  reg clk = 0;
  reg [3:0] count = 0;
  always #5 clk = ~clk;
  always @(posedge clk) count <= count + 1;
  initial begin
    $dumpfile("wave.vcd");
    $dumpvars(0, counter_tb);
    #200;
    $display("Final count = %0d", count);
    $finish;
  end
endmodule
