import random
import numpy as np
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.en.value = 0
    dut.a_in.value = 0
    dut.b_in.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0

@cocotb.test()
async def dot_product(dut):
    """Stream two int8 vectors through: acc must equal their dot product (one output of a matmul)."""
    await start(dut)
    a = np.random.randint(-128, 128, size=16)
    b = np.random.randint(-128, 128, size=16)
    dut.en.value = 1
    for x, w in zip(a, b):
        dut.a_in.value = int(x)
        dut.b_in.value = int(w)
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    expected = int(np.dot(a.astype(np.int64), b.astype(np.int64)))
    got = dut.acc.value.to_signed()
    assert got == expected, f"dot product: expected {expected}, got {got}"

@cocotb.test()
async def worst_case(dut):
    """-128 * -128 repeatedly: the largest product, checks the accumulator width and signs."""
    await start(dut)
    dut.en.value = 1
    for n in range(1, 101):
        dut.a_in.value = -128
        dut.b_in.value = -128
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        assert dut.acc.value.to_signed() == 16384 * n, f"after {n} MACs got {dut.acc.value.to_signed()}"

@cocotb.test()
async def random_with_stalls_and_resets(dut):
    """Random data, enable and resets, checked every cycle against a Python model."""
    await start(dut)
    acc = a_out = b_out = 0
    for _ in range(2000):
        a = random.randint(-128, 127)
        b = random.randint(-128, 127)
        en = 1 if random.random() < 0.8 else 0
        rst = 1 if random.random() < 0.02 else 0
        dut.a_in.value, dut.b_in.value = a, b
        dut.en.value, dut.rst.value = en, rst
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        if rst:
            acc = a_out = b_out = 0
        elif en:
            acc, a_out, b_out = acc + a * b, a, b
        assert dut.acc.value.to_signed() == acc, f"acc: expected {acc}, got {dut.acc.value.to_signed()}"
        assert dut.a_out.value.to_signed() == a_out, "a_out wrong (pass-through)"
        assert dut.b_out.value.to_signed() == b_out, "b_out wrong (pass-through)"
