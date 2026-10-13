.section .text.start
.global _start
_start:
    li   sp, 0x20000          # stack at top of the 128 KB testbench memory
    call main
    bnez a0, 1f               # only signal success if main returned 0
    li   t0, 0x20000000
    li   t1, 123456789        # magic value the testbench checks for
    sw   t1, 0(t0)
1:  ebreak                    # stop the CPU -> testbench ends simulation
