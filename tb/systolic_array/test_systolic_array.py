"""cocotb tests for systolic_array #(N) (output-stationary, option a, per-column drain).

Same checks as test_array2x2, generalised to any N with flat ports:
  a       [N*8-1:0]   row i's input in bits [i*8 +: 8]
  b       [N*8-1:0]   column j's input in bits [j*8 +: 8]
  res_out [N*32-1:0]  column j's drain output in bits [j*32 +: 32]

The testbench plays the future skew module and controller:
  * skew: row i of A and column j of B delayed by i and j cycles, zeros outside the tile
  * compute for K + 2N - 2 enabled cycles
  * drain for N enabled cycles, reading the bottom row before each shift
    (results arrive bottom row first)
N comes from the environment (set by the Makefile), and must match the design's parameter.
"""

import os
import random

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

N = int(os.environ.get("N", "4"))


def pack(values, width):
    """Pack signed integers into one flat bus, element 0 in the lowest bits."""
    mask = (1 << width) - 1
    word = 0
    for idx, v in enumerate(values):
        word |= (int(v) & mask) << (idx * width)
    return word


def unpack_signed(word, count, width):
    """Split a flat bus into signed integers, element 0 from the lowest bits."""
    out = []
    for idx in range(count):
        v = (word >> (idx * width)) & ((1 << width) - 1)
        if v & (1 << (width - 1)):
            v -= 1 << width
        out.append(v)
    return out


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.a.value = 0
    dut.b.value = 0
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
    K = A.shape[1]

    # Compute phase: K + 2N - 2 enabled cycles. Inputs only advance on enabled cycles.
    dut.drain.value = 0
    step = 0
    while step < K + 2 * N - 2:
        en = enable(stall_prob)
        a_vals = [int(A[i, step - i]) if 0 <= step - i < K else 0 for i in range(N)]
        b_vals = [int(B[step - j, j]) if 0 <= step - j < K else 0 for j in range(N)]
        dut.a.value = pack(a_vals, 8)
        dut.b.value = pack(b_vals, 8)
        dut.en.value = en
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        step += en

    # Drain phase: N enabled shifts. Read the bottom row before each shift.
    dut.a.value = 0
    dut.b.value = 0
    dut.drain.value = 1
    C = np.zeros((N, N), dtype=np.int64)
    shifts = 0
    while shifts < N:
        en = enable(stall_prob)
        if en:
            row = N - 1 - shifts  # bottom row comes out first
            C[row, :] = unpack_signed(int(dut.res_out.value), N, 32)
        dut.en.value = en
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        shifts += en

    # After a full drain every accumulator must be zero.
    assert unpack_signed(int(dut.res_out.value), N, 32) == [0] * N, "array not cleared after drain"
    dut.drain.value = 0
    dut.en.value = 0
    return C


def check(A, B, C):
    want = A.astype(np.int64) @ B.astype(np.int64)
    assert np.array_equal(C, want), f"\nA=\n{A}\nB=\n{B}\ngot=\n{C}\nwant=\n{want}"


def rand_mat(rows, cols):
    m = np.random.randint(-128, 128, size=(rows, cols))
    if random.random() < 0.5:
        m[random.randrange(rows), random.randrange(cols)] = -128
    if random.random() < 0.5:
        m[random.randrange(rows), random.randrange(cols)] = 127
    return m


@cocotb.test()
async def test_identity(dut):
    """A x I = A: an easy-to-read first check that every row and column is wired."""
    await setup(dut)
    A = np.arange(N * N).reshape(N, N) - (N * N) // 2
    B = np.eye(N, dtype=int)
    check(A, B, await run_tile(dut, A, B))


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
    """100 random tiles back to back, K from 1 to 2N + 4, no reset between tiles."""
    random.seed(10 + N)
    np.random.seed(10 + N)
    await setup(dut)
    for _ in range(100):
        K = random.randint(1, 2 * N + 4)
        A, B = rand_mat(N, K), rand_mat(K, N)
        check(A, B, await run_tile(dut, A, B))


@cocotb.test()
async def test_random_tiles_with_stalls(dut):
    """100 random tiles with en dropped on about 30% of cycles in compute and drain."""
    random.seed(20 + N)
    np.random.seed(20 + N)
    await setup(dut)
    for _ in range(100):
        K = random.randint(1, 2 * N + 4)
        A, B = rand_mat(N, K), rand_mat(K, N)
        check(A, B, await run_tile(dut, A, B, stall_prob=0.3))


@cocotb.test()
async def test_reset_mid_tile(dut):
    """Reset part-way through a tile, then the next tile must still be correct."""
    random.seed(30 + N)
    np.random.seed(30 + N)
    await setup(dut)
    A, B = rand_mat(N, 6), rand_mat(6, N)
    for step in range(3):
        dut.a.value = pack([int(A[i, step - i]) if 0 <= step - i < 6 else 0 for i in range(N)], 8)
        dut.b.value = pack([int(B[step - j, j]) if 0 <= step - j < 6 else 0 for j in range(N)], 8)
        dut.en.value = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    A, B = rand_mat(N, 5), rand_mat(5, N)
    check(A, B, await run_tile(dut, A, B))
