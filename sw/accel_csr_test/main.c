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


static uint64_t cycles(void) {
    timer0_uptime_latch_write(1);
    return timer0_uptime_cycles_read();
}

int main(void) {
#ifdef CONFIG_CPU_HAS_INTERRUPT
    irq_setmask(0);
    irq_setie(1);
#endif
    uart_init();
    printf("\nCSR test for SoC\n\n");

    
    // Test 1: After reset, done reads 0 and busy reads 0.
    
    {
        uint8_t done_val = accel_done_read();
        uint8_t busy_val = accel_busy_read();

        if ((done_val == 0) && (busy_val == 0)) {
            printf("1. Reset state (done=0, busy=0): PASS\n");
        } else {
            printf("1. Reset state (done=%u, busy=%u): FAIL\n", done_val, busy_val);
        }
    }

    
    // Test 2: Write K, write start, and busy reads 1 straight afterwards.
    // (Using large K=1000 so it stays running)
    // Test 3: Poll until done reads 1 (with timeout counter), then check busy reads 0.
    
    {
        accel_K_write(1000);
        accel_control_write(1); // Triggers the start pulse

        uint8_t busy_val_after_start = accel_busy_read();

        int timeout_counter = 0;
        while ((accel_done_read() == 0) && (timeout_counter < 2000)) {
            timeout_counter++;
        }

        if (timeout_counter >= 2000) {
            printf("2/3. Poll done=1: TIMEOUT FAILURE - timed out after 2000 polls\n");
        } else {
            uint8_t busy_val = accel_busy_read();
            uint8_t done_val = accel_done_read();

            if (busy_val_after_start == 1) {
                printf("2. Busy straight after start (K=1000): PASS\n");
            } else {
                printf("2. Busy straight after start (busy=%u): FAIL\n", busy_val_after_start);
            }

            if ((done_val == 1) && (busy_val == 0)) {
                printf("3. Poll done=1 and busy=0: PASS (completed in %d polls)\n", timeout_counter);
            } else {
                printf("3. Poll done=1 and busy=0 (done=%u, busy=%u): FAIL (polls: %d)\n", done_val, busy_val, timeout_counter);
            }
        }
    }

    
    // Test 4: Read done several more times: it stays 1 (no side effect).
    
    {
        uint8_t r1 = accel_done_read();
        uint8_t r2 = accel_done_read();
        uint8_t r3 = accel_done_read();

        if ((r1 == 1) && (r2 == 1) && (r3 == 1)) {
            printf("4. Multiple reads of done (no side effect): PASS\n");
        } else {
            printf("4. Multiple reads of done (r1=%u, r2=%u, r3=%u): FAIL\n", r1, r2, r3);
        }
    }

    
    // Test 5: Write start again: done reads 0 straight afterwards, 
    // then 1 once that tile finishes. (Using small K=10 for speed)
    
    {
        accel_K_write(10);
        accel_control_write(1); // Start new tile

        uint8_t immediate_done = accel_done_read();

        int timeout_counter = 0;
        while ((accel_done_read() == 0) && (timeout_counter < 2000)) {
            timeout_counter++;
        }

        if (timeout_counter >= 2000) {
            printf("5. Restart: TIMEOUT FAILURE - timed out after 2000 polls\n");
        } else {
            uint8_t final_done = accel_done_read();

            if ((immediate_done == 0) && (final_done == 1)) {
                printf("5. Restart clears done to 0, then sets to 1 on completion: PASS (polls: %d)\n", timeout_counter);
            } else {
                printf("5. Restart behavior (immediate=%u, final=%u): FAIL (polls: %d)\n", immediate_done, final_done, timeout_counter);
            }
        }
    }

    
    // Bonus: Tile Execution Timing Measurement
    
    {
        // 1. Measure timer overhead
        uint64_t o0 = cycles();
        uint64_t o1 = cycles();
        uint32_t overhead = (uint32_t)(o1 - o0);
        printf("\nPerformance Measurement\n");
        printf("Timer Overhead : %u cycles\n", (unsigned)overhead);
        printf("%-6s | %-12s | %-12s | %-10s | %-10s\n", "K", "Net Cycles", "Expected", "Diff", "Polls");
        printf("-----------------------------------------------------------\n");

        int k_values[] = {8, 16, 32, 64, 128};
        int num_k = sizeof(k_values) / sizeof(k_values[0]);

        for (int idx = 0; idx < num_k; idx++) {
            int k = k_values[idx];
            accel_K_write(k);

            uint64_t t0 = cycles();
            accel_control_write(1); // Start execution

            int timeout_counter = 0;
            while ((accel_done_read() == 0) && (timeout_counter < 50000)) {
                timeout_counter++;
            }
            uint64_t t1 = cycles();

            if (timeout_counter >= 50000) {
                printf("K=%-4d | TIMEOUT FAILURE\n", k);
            } else {
                uint32_t total_cycles = (uint32_t)(t1 - t0);
                uint32_t net_cycles = (total_cycles > overhead) ? (total_cycles - overhead) : 0;
                uint32_t expected_cycles = k + (3 * N) - 2;
                int diff = (int)net_cycles - (int)expected_cycles;

                printf("%-6d | %-12u | %-12u | %-10d | %-10d\n", 
                       k, (unsigned)net_cycles, (unsigned)expected_cycles, diff, timeout_counter);
            }
        }
    }

    printf("\nTest complete\n");
    while (1);
    return 0;
}