"""cocotb tests for skew #(N).

Intended behaviour, checked every cycle against an independent model:
  * lane k of a_out / b_out = lane k of a_in / b_in as it was k enabled clock edges ago
    (lane 0 passes straight through, with no delay)
  * before k enabled edges have happened since reset, lane k outputs 0
  * en = 0: nothing moves (the delay counts enabled edges only)
  * rst: every delayed lane goes back to 0
The model keeps a list of the inputs captured at each enabled edge; it does not copy
the register structure of the design.
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

N = int(os.environ.get("N", "4"))


def pack(values):
    word = 0
    for idx, v in enumerate(values):
        word |= (int(v) & 0xFF) << (idx * 8)
    return word


def unpack(word):
    out = []
    for idx in range(N):
        v = (word >> (idx * 8)) & 0xFF
        out.append(v - 256 if v & 0x80 else v)
    return out


class SkewModel:
    def __init__(self):
        self.history = []  # input vectors captured at each enabled edge since reset

    def expected(self, current):
        """Expected outputs given the inputs currently applied (lane 0 is combinational)."""
        out = []
        for k in range(N):
            if k == 0:
                out.append(current[0])
            elif len(self.history) >= k:
                out.append(self.history[-k][k])
            else:
                out.append(0)
        return out

    def clock_edge(self, rst, en, current):
        if rst:
            self.history = []
        elif en:
            self.history.append(list(current))


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.a_in.value = 0
    dut.b_in.value = 0
    dut.en.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    return SkewModel(), SkewModel()


async def cycle(dut, ma, mb, a, b, en=1, rst=0):
    """Apply inputs after a falling edge, check outputs, then let the rising edge happen."""
    dut.a_in.value = pack(a)
    dut.b_in.value = pack(b)
    dut.en.value = en
    dut.rst.value = rst
    await Timer(1, unit="ns")  # let lane 0's combinational path settle
    got_a, got_b = unpack(int(dut.a_out.value)), unpack(int(dut.b_out.value))
    want_a, want_b = ma.expected(a), mb.expected(b)
    assert got_a == want_a, f"a_out: got {got_a}, expected {want_a} (history {len(ma.history)})"
    assert got_b == want_b, f"b_out: got {got_b}, expected {want_b} (history {len(mb.history)})"
    await RisingEdge(dut.clk)
    ma.clock_edge(rst, en, a)
    mb.clock_edge(rst, en, b)
    await FallingEdge(dut.clk)


def rand_vec():
    return [random.choice([-128, 127, 0, random.randint(-128, 127)]) for _ in range(N)]


@cocotb.test()
async def test_staircase(dut):
    """Distinct values per step make each lane's delay easy to read in a waveform."""
    ma, mb = await setup(dut)
    dut.rst.value = 0
    for t in range(3 * N):
        a = [((t * 10 + k) % 256) - 128 for k in range(N)]
        b = [((t * 10 + k + 5) % 256) - 128 for k in range(N)]
        await cycle(dut, ma, mb, a, b)


@cocotb.test()
async def test_random_with_stalls(dut):
    """5,000 cycles of random inputs with en low about 30% of the time."""
    random.seed(40 + N)
    ma, mb = await setup(dut)
    dut.rst.value = 0
    for _ in range(5000):
        await cycle(dut, ma, mb, rand_vec(), rand_vec(), en=int(random.random() > 0.3))


@cocotb.test()
async def test_reset_clears(dut):
    """Fill the delay lines, reset, then check every delayed lane restarts from 0."""
    random.seed(50 + N)
    ma, mb = await setup(dut)
    dut.rst.value = 0
    for _ in range(2 * N):
        await cycle(dut, ma, mb, rand_vec(), rand_vec())
    await cycle(dut, ma, mb, rand_vec(), rand_vec(), rst=1)
    for _ in range(2 * N):
        await cycle(dut, ma, mb, rand_vec(), rand_vec())


@cocotb.test()
async def test_random_resets(dut):
    """Random inputs, stalls and occasional resets mixed together."""
    random.seed(60 + N)
    ma, mb = await setup(dut)
    dut.rst.value = 0
    for _ in range(3000):
        await cycle(
            dut, ma, mb, rand_vec(), rand_vec(),
            en=int(random.random() > 0.3),
            rst=int(random.random() < 0.02),
        )
