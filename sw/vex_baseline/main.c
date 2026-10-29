#include <stdio.h>
#include <stdint.h>
#include <irq.h>
#include <libbase/uart.h>
#include <generated/csr.h>
#include <system.h>

#ifndef CSR_TIMER0_UPTIME_CYCLES_ADDR
#error "Rebuild the SoC with --timer-uptime"
#endif

#define N 8

static int8_t  A[N][N], B[N][N];
static int32_t C[N][N];

static uint64_t cycles(void) {
    timer0_uptime_latch_write(1);
    return timer0_uptime_cycles_read();
}

/* identical to the PicoRV32 version */
__attribute__((noinline)) static void matmul(int n) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++) {
            int32_t acc = 0;
            for (int k = 0; k < n; k++)
                acc += (int32_t)A[i][k] * (int32_t)B[k][j];
            C[i][j] = acc;
        }
}

int main(void) {
#ifdef CONFIG_CPU_HAS_INTERRUPT
    irq_setmask(0);
    irq_setie(1);
#endif
    uart_init();
    printf("\nint8 matmul baseline on VexRiscv\n");

    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            A[i][j] = (int8_t)(i * 3 + j * 5 - 20);
            B[i][j] = (int8_t)(i * 7 - j * 2 + 3);
        }

    /* cost of reading the timer itself, subtracted from every result */
    uint64_t o0 = cycles();
    uint64_t o1 = cycles();
    uint32_t overhead = (uint32_t)(o1 - o0);
    printf("timer overhead: %u cycles\n", (unsigned)overhead);

    for (int n = 4; n <= 8; n += 4) {
        for (int run = 0; run < 2; run++) {          /* run 0 = cold cache, run 1 = warm */
            if (run == 0) {
                flush_cpu_icache();                  /* empty the instruction cache */
                flush_cpu_dcache();                  /* empty the data cache */
            }
            uint64_t t0 = cycles();
            matmul(n);
            uint64_t t1 = cycles();

            int32_t checksum = 0;
            for (int i = 0; i < n; i++)
                for (int j = 0; j < n; j++) checksum += C[i][j];

            printf("%dx%d int8 matmul (%s): %u cycles, checksum %ld\n",
                   n, n, run ? "warm" : "cold",
                   (unsigned)(t1 - t0 - overhead), (long)checksum);
        }
        if (n == 4) {
            for (int i = 0; i < 4; i++) {
                for (int j = 0; j < 4; j++) printf("%ld ", (long)C[i][j]);
                printf("\n");
            }
        }
    }
    while (1);
    return 0;
}