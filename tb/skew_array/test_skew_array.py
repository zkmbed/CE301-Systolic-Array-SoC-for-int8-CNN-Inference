"""skew + systolic_array together: feed UNSKEWED inputs and check against NumPy.

Each compute step t applies column t of A and row t of B unchanged (zeros after K).
The skew module must create the delays itself. Compute for K + 2N - 2 enabled cycles,
then drain N enabled cycles, reading the bottom row before each shift.
"""

import os
import random

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

N = int(os.environ.get("N", "4"))


def pack(values, width):
    return sum((int(v) & ((1 << width) - 1)) << (i * width) for i, v in enumerate(values))


def unpack_signed(word, count, width):
    out = []
    for i in range(count):
        v = (word >> (i * width)) & ((1 << width) - 1)
        out.append(v - (1 << width) if v >> (width - 1) else v)
    return out


@cocotb.test()
async def test_unskewed_inputs(dut):
    """100 random tiles, every other one with en stalls, inputs not skewed by the testbench."""
    random.seed(5 + N)
    np.random.seed(5 + N)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.a.value = 0
    dut.b.value = 0
    dut.en.value = 0
    dut.drain.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0

    for tile in range(100):
        K = random.randint(1, 2 * N + 4)
        A = np.random.randint(-128, 128, (N, K))
        B = np.random.randint(-128, 128, (K, N))
        stall = 0.2 if tile % 2 else 0.0

        dut.drain.value = 0
        step = 0
        while step < K + 2 * N - 2:
            en = 0 if random.random() < stall else 1
            dut.a.value = pack([A[i, step] if step < K else 0 for i in range(N)], 8)
            dut.b.value = pack([B[step, j] if step < K else 0 for j in range(N)], 8)
            dut.en.value = en
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            step += en

        dut.a.value = 0
        dut.b.value = 0
        dut.drain.value = 1
        C = np.zeros((N, N), dtype=np.int64)
        shifts = 0
        while shifts < N:
            en = 0 if random.random() < stall else 1
            if en:
                C[N - 1 - shifts, :] = unpack_signed(int(dut.res_out.value), N, 32)
            dut.en.value = en
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            shifts += en
        dut.drain.value = 0

        want = A.astype(np.int64) @ B.astype(np.int64)
        assert np.array_equal(C, want), f"tile {tile}\ngot\n{C}\nwant\n{want}"
