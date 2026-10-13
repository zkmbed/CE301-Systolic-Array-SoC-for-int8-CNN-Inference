import random
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def corner_cases(dut):
    """The values most likely to expose sign or width bugs."""
    for a, b in [(0, 0), (1, 1), (-1, 1), (-1, -1), (127, 127),
                 (-128, -128), (-128, 127), (5, -3)]:
        dut.a.value = a
        dut.b.value = b
        await Timer(1)
        got = dut.p.value.to_signed()
        assert got == a * b, f"{a} * {b}: expected {a*b}, got {got}"

@cocotb.test()
async def random_values(dut):
    """1000 random pairs across the full int8 range."""
    for _ in range(1000):
        a = random.randint(-128, 127)
        b = random.randint(-128, 127)
        dut.a.value = a
        dut.b.value = b
        await Timer(1)
        got = dut.p.value.to_signed()
        assert got == a * b, f"{a} * {b}: expected {a*b}, got {got}"
