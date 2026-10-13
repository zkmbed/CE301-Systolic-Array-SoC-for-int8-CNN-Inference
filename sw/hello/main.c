#include <stdint.h>

#define OUTPORT 0x10000000          /* testbench prints anything written here */
#define N 8

static int8_t  A[N][N], B[N][N];
static int32_t C[N][N];

static void putc_(char c) { *(volatile uint32_t *)OUTPORT = c; }
static void puts_(const char *s) { while (*s) putc_(*s++); }
static void putint(int32_t v) {
    char buf[12]; int i = 0; uint32_t u;
    if (v < 0) { putc_('-'); u = -(uint32_t)v; } else u = v;
    do { buf[i++] = '0' + u % 10; u /= 10; } while (u);
    while (i) putc_(buf[--i]);
}
static inline uint32_t rdcycle(void) {
    uint32_t c; asm volatile ("rdcycle %0" : "=r"(c)); return c;
}

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
    puts_("Hello from my own C program on PicoRV32!\n");

    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            A[i][j] = (int8_t)(i * 3 + j * 5 - 20);
            B[i][j] = (int8_t)(i * 7 - j * 2 + 3);
        }

    for (int n = 4; n <= 8; n += 4) {
        uint32_t t0 = rdcycle();
        matmul(n);
        uint32_t t1 = rdcycle();

        int32_t checksum = 0;
        for (int i = 0; i < n; i++)
            for (int j = 0; j < n; j++) checksum += C[i][j];

        putint(n); puts_("x"); putint(n);
        puts_(" int8 matmul: "); putint((int32_t)(t1 - t0));
        puts_(" cycles, checksum "); putint(checksum); puts_("\n");

        if (n == 4) {
            for (int i = 0; i < 4; i++) {
                for (int j = 0; j < 4; j++) { putint(C[i][j]); puts_(" "); }
                puts_("\n");
            }
        }
    }
    return 0;
}
