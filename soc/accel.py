from migen import *
from litex.gen import LiteXModule
import os
class Accel (LiteXModule):
    def __init__ (self, platform, N, K_max):

        self.N = N
        self.K_max = K_max
        self.busy = Signal(1)
        self.in_valid = Signal(1)
        self.out_ready = Signal(1)
        self.in_ready = Signal(1)
        self.out_valid = Signal(1)
        self.done = Signal(1)
        self.K = Signal(K_max.bit_length())
        self.a_in_TOP = Signal((N*8))
        self.b_in_TOP = Signal((N*8))
        self.res_out_TOP = Signal((N*32))
        
        
        self.dir=os.path.dirname(os.path.abspath(__file__))
        platform.add_source(os.path.join(self.dir, "..", "rtl", "accel_core.v"))
        platform.add_source(os.path.join(self.dir, "..", "rtl", "controller.v"))
        platform.add_source(os.path.join(self.dir, "..", "rtl", "systolic_array.v"))
        platform.add_source(os.path.join(self.dir, "..", "rtl", "skew.v"))
        platform.add_source(os.path.join(self.dir, "..", "rtl", "mac_pe.v"))

        self.specials += Instance("accel_core",

            i_clk = ClockSignal("sys"),
            i_rst = ResetSignal("sys"),
            p_K_max = Instance.PreformattedParam(str(K_max)),
            p_N = Instance.PreformattedParam(str(N)),
            i_K = self.K,
            i_start = 0,
            o_busy = self.busy,
            i_in_valid = self.in_valid,
            i_out_ready = self.out_ready,
            o_in_ready = self.in_ready,
            o_out_valid = self.out_valid,
            o_done = self.done,
            i_a_in_TOP = self.a_in_TOP,
            i_b_in_TOP = self.b_in_TOP,
            o_res_out_TOP = self.res_out_TOP
        )