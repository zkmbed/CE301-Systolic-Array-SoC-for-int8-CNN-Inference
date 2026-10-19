"""cocotb tests for array2x2 (output-stationary, option a, per-column drain).

The testbench plays the role of the future skew module and controller:
  * skew: row i of A and column j of B are delayed by i and j cycles, with zeros
    outside the tile, so PE(i,j) sees A[i][k] and B[k][j] together at step k + i + j
  * compute for K + 2N - 2 enabled cycles (the last PE's final product lands then)
  * drain for N enabled cycles, reading the bottom row before each shift;
    results arrive bottom row first, so they are written back in reverse row order
Every tile's result is compared with NumPy. Tiles run back to back without reset,
which checks that each drain leaves every accumulator at zero.
"""

import random

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

N = 2


def ports(dut):
    a = [dut.a_in1, dut.a_in2]
    b = [dut.b_in1, dut.b_in2]
    res = [dut.res_out1, dut.res_out2]
    return a, b, res


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    a, b, _ = ports(dut)
    for p in a + b:
        p.value = 0
    dut.en.value = 0
    dut.drain.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


def enable(stall_prob):
    return 0 if random.random() < stall_prob else 1


async def run_tile(dut, A, B, stall_prob=0.0):
    """Feed one tile (A is N x K, B is K x N), drain it, return the N x N result."""
    a, b, res = ports(dut)
    K = A.shape[1]

    # Compute phase: K + 2N - 2 enabled cycles. Inputs only advance on enabled cycles.
    dut.drain.value = 0
    step = 0
    while step < K + 2 * N - 2:
        en = enable(stall_prob)
        for i in range(N):
            k = step - i
            a[i].value = int(A[i, k]) if 0 <= k < K else 0
        for j in range(N):
            k = step - j
            b[j].value = int(B[k, j]) if 0 <= k < K else 0
        dut.en.value = en
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        step += en

    # Drain phase: N enabled shifts. Read the bottom row before each shift.
    for p in a + b:
        p.value = 0
    dut.drain.value = 1
    C = np.zeros((N, N), dtype=np.int64)
    shifts = 0
    while shifts < N:
        en = enable(stall_prob)
        if en:
            row = N - 1 - shifts  # bottom row comes out first
            for j in range(N):
                C[row, j] = res[j].value.to_signed()
        dut.en.value = en
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        shifts += en

    # After a full drain the bottom outputs (and every accumulator) must be zero.
    for j in range(N):
        assert res[j].value.to_signed() == 0, f"column {j} not cleared after drain"
    dut.drain.value = 0
    dut.en.value = 0
    return C


def check(A, B, C):
    want = A.astype(np.int64) @ B.astype(np.int64)
    assert np.array_equal(C, want), f"\nA=\n{A}\nB=\n{B}\ngot=\n{C}\nwant=\n{want}"


def rand_mat(rows, cols):
    m = np.random.randint(-128, 128, size=(rows, cols))
    # force some extreme values into most tiles
    if random.random() < 0.5:
        m[random.randrange(rows), random.randrange(cols)] = -128
    if random.random() < 0.5:
        m[random.randrange(rows), random.randrange(cols)] = 127
    return m


@cocotb.test()
async def test_example(dut):
    """The hand-worked example: [[1,2],[3,4]] x [[5,6],[7,8]] = [[19,22],[43,50]]."""
    await setup(dut)
    A = np.array([[1, 2], [3, 4]])
    B = np.array([[5, 6], [7, 8]])
    C = await run_tile(dut, A, B)
    check(A, B, C)


@cocotb.test()
async def test_worst_case(dut):
    """All -128 (largest product) and -128 x 127 (most negative), with a long K."""
    await setup(dut)
    K = 16
    A = np.full((N, K), -128)
    check(A, np.full((K, N), -128), await run_tile(dut, A, np.full((K, N), -128)))
    check(A, np.full((K, N), 127), await run_tile(dut, A, np.full((K, N), 127)))


@cocotb.test()
async def test_random_tiles(dut):
    """200 random tiles back to back, K from 1 to 12, no reset between tiles."""
    random.seed(1)
    np.random.seed(1)
    await setup(dut)
    for _ in range(200):
        K = random.randint(1, 12)
        A, B = rand_mat(N, K), rand_mat(K, N)
        check(A, B, await run_tile(dut, A, B))


@cocotb.test()
async def test_random_tiles_with_stalls(dut):
    """200 random tiles with en dropped on about 30% of cycles in compute and drain."""
    random.seed(2)
    np.random.seed(2)
    await setup(dut)
    for _ in range(200):
        K = random.randint(1, 12)
        A, B = rand_mat(N, K), rand_mat(K, N)
        check(A, B, await run_tile(dut, A, B, stall_prob=0.3))


@cocotb.test()
async def test_reset_mid_tile(dut):
    """Reset part-way through a tile, then the next tile must still be correct."""
    random.seed(3)
    np.random.seed(3)
    await setup(dut)
    a, b, _ = ports(dut)
    A, B = rand_mat(N, 6), rand_mat(6, N)
    # start a tile, abandon it after 3 cycles with a reset
    for step in range(3):
        for i in range(N):
            a[i].value = int(A[i, step - i]) if 0 <= step - i < 6 else 0
        for j in range(N):
            b[j].value = int(B[step - j, j]) if 0 <= step - j < 6 else 0
        dut.en.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    A, B = rand_mat(N, 5), rand_mat(5, N)
    check(A, B, await run_tile(dut, A, B))
