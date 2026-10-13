import random
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def random_adds(dut):
    for _ in range(100):
        a = random.randint(0, 255)
        b = random.randint(0, 255)
        dut.a.value = a
        dut.b.value = b
        await Timer(1)
        assert int(dut.y.value) == a + b, f"{a}+{b} gave {int(dut.y.value)}"
