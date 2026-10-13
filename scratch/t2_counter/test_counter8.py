import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

async def reset(dut):
    dut.rst.value = 1
    dut.en.value = 0
    await RisingEdge(dut.clk)     # reset is captured on this edge
    await FallingEdge(dut.clk)    # move to mid-cycle before changing inputs
    dut.rst.value = 0

@cocotb.test()
async def counts_and_wraps(dut):
    """Hold enable high for 300 cycles: must count up and wrap 255 -> 0."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)
    assert dut.count.value.to_unsigned() == 0, "count not 0 after reset"
    dut.en.value = 1
    for cycle in range(1, 301):
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        expected = cycle % 256
        got = dut.count.value.to_unsigned()
        assert got == expected, f"cycle {cycle}: expected {expected}, got {got}"

@cocotb.test()
async def random_enable_and_reset(dut):
    """Random enable and occasional reset, checked against a Python model."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)
    model = 0
    for _ in range(1000):
        en = random.randint(0, 1)
        rst = 1 if random.random() < 0.05 else 0
        dut.en.value = en
        dut.rst.value = rst
        await RisingEdge(dut.clk)      # the register updates here
        await FallingEdge(dut.clk)     # look half a cycle later, once it's settled
        if rst:
            model = 0
        elif en:
            model = (model + 1) % 256
        got = dut.count.value.to_unsigned()
        assert got == model, f"expected {model}, got {got} (en={en}, rst={rst})"
