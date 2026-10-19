"""cocotb tests for mac_pe (option a: no first/last; acc doubles as the drain shift register).

Each test drives inputs just after a falling edge and checks outputs just after the
next rising edge, against a cycle-accurate Python model of the intended behaviour:

    rst            -> acc = 0, a_out = 0, b_out = 0          (beats everything)
    not drain, en  -> a_out = a_in, b_out = b_in, acc += a_in * b_in
    drain, en      -> acc = acc_in                            (a_out, b_out hold)
    not en         -> everything holds
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


def wrap32(x):
    """Two's-complement wrap to a signed 32-bit value, as the hardware register does."""
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x & 0x80000000 else x


class PEModel:
    def __init__(self):
        self.acc = 0
        self.a_out = 0
        self.b_out = 0

    def step(self, rst, en, drain, a_in, b_in, acc_in):
        if rst:
            self.acc, self.a_out, self.b_out = 0, 0, 0
        elif not drain:
            if en:
                self.a_out, self.b_out = a_in, b_in
                self.acc = wrap32(self.acc + a_in * b_in)
        else:
            if en:
                self.acc = wrap32(acc_in)


async def setup(dut):
    """Start the clock and reset the PE; returns a fresh model."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.en.value = 0
    dut.drain.value = 0
    dut.a_in.value = 0
    dut.b_in.value = 0
    dut.acc_in.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    return PEModel()


async def cycle(dut, model, rst=0, en=1, drain=0, a_in=0, b_in=0, acc_in=0):
    """Apply one cycle of inputs, then check the outputs against the model."""
    await FallingEdge(dut.clk)
    dut.rst.value = rst
    dut.en.value = en
    dut.drain.value = drain
    dut.a_in.value = a_in
    dut.b_in.value = b_in
    dut.acc_in.value = acc_in
    model.step(rst, en, drain, a_in, b_in, acc_in)
    await RisingEdge(dut.clk)
    await ReadOnly()
    got = (dut.acc.value.to_signed(), dut.a_out.value.to_signed(), dut.b_out.value.to_signed())
    want = (model.acc, model.a_out, model.b_out)
    assert got == want, (
        f"rst={rst} en={en} drain={drain} a_in={a_in} b_in={b_in} acc_in={acc_in}: "
        f"got (acc, a_out, b_out) = {got}, expected {want}"
    )


@cocotb.test()
async def test_reset(dut):
    """Reset clears acc and both pass-through registers."""
    model = await setup(dut)
    for _ in range(3):
        await cycle(dut, model, a_in=5, b_in=-7)
    await cycle(dut, model, rst=1, a_in=5, b_in=-7)
    assert dut.acc.value.to_signed() == 0


@cocotb.test()
async def test_dot_product(dut):
    """A known signed dot product accumulates correctly, and A/B pass through one cycle late."""
    model = await setup(dut)
    a = [3, -4, 127, -128, 0, 50]
    b = [7, 9, -2, -128, 99, -50]
    for x, y in zip(a, b):
        await cycle(dut, model, a_in=x, b_in=y)
    assert dut.acc.value.to_signed() == sum(x * y for x, y in zip(a, b))


@cocotb.test()
async def test_worst_case_products(dut):
    """-128 x -128 (the largest product, 16,384) repeated, plus the most negative product."""
    model = await setup(dut)
    for _ in range(8):
        await cycle(dut, model, a_in=-128, b_in=-128)
    assert dut.acc.value.to_signed() == 8 * 16384
    await cycle(dut, model, rst=1)
    for _ in range(8):
        await cycle(dut, model, a_in=-128, b_in=127)
    assert dut.acc.value.to_signed() == 8 * -16256


@cocotb.test()
async def test_enable_holds(dut):
    """With en low, nothing changes in compute mode or in drain mode."""
    model = await setup(dut)
    await cycle(dut, model, a_in=10, b_in=10)
    for _ in range(4):
        await cycle(dut, model, en=0, a_in=99, b_in=99)
    for _ in range(4):
        await cycle(dut, model, en=0, drain=1, acc_in=12345)
    assert dut.acc.value.to_signed() == 100


@cocotb.test()
async def test_drain_shifts(dut):
    """In drain mode acc takes acc_in each enabled cycle; a_out and b_out hold."""
    model = await setup(dut)
    await cycle(dut, model, a_in=6, b_in=-7)
    for v in [100, -200, 0, 2**31 - 1, -(2**31)]:
        await cycle(dut, model, drain=1, acc_in=v, a_in=55, b_in=55)
    await cycle(dut, model, drain=1, en=0, acc_in=777)  # stalled mid-drain: hold


@cocotb.test()
async def test_reset_beats_drain(dut):
    """Reset wins even when drain and en are both high."""
    model = await setup(dut)
    await cycle(dut, model, a_in=9, b_in=9)
    await cycle(dut, model, rst=1, drain=1, en=1, acc_in=4242)
    assert dut.acc.value.to_signed() == 0


@cocotb.test()
async def test_random(dut):
    """5,000 cycles of random inputs in every mode, checked against the model every cycle."""
    random.seed(301)
    model = await setup(dut)
    for _ in range(5000):
        await cycle(
            dut,
            model,
            rst=int(random.random() < 0.02),
            en=int(random.random() < 0.85),
            drain=int(random.random() < 0.25),
            a_in=random.randint(-128, 127),
            b_in=random.randint(-128, 127),
            acc_in=random.randint(-(2**31), 2**31 - 1),
        )
