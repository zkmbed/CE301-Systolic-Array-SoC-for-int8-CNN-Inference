from migen import *
from litex.gen import LiteXModule
from litex.soc.interconnect.csr import CSRField, CSRStatus, CSRStorage
import os
class Accel (LiteXModule):
    def __init__ (self, platform, N, K_max):

        self.N = N
        self.K_max = K_max
        self.sticky = Signal(1)
        self.busy_sig = Signal(1)
        self.in_valid = Signal(1)
        self.out_ready = Signal(1)
        self.in_ready = Signal(1)
        self.out_valid = Signal(1)
        self.done_sig = Signal(1)
        self.K_sig = Signal(K_max.bit_length())
        self.a_in_TOP = Signal((N*8))
        self.b_in_TOP = Signal((N*8))
        self.res_out_TOP = Signal((N*32))

        self.K = CSRStorage(K_max.bit_length(), description="K config")
        self.control = CSRStorage(fields = [CSRField("start", 1, pulse=True)],description="start flag")
        self.busy = CSRStatus(1, description="busy flag")
        self.done = CSRStatus(1, description="done flag")
        

        self.comb += [
            self.K_sig.eq(self.K.storage),
            self.busy.status.eq(self.busy_sig),
            self.done.status.eq(self.sticky),
            self.in_valid.eq(1), #temp for csr test
            self.out_ready.eq(1) #temp for csr test
        ]
        
        self.sync +=(If(self.done_sig==1, self.sticky.eq(1)).Elif((self.done_sig==0) & (self.busy_sig==0) & (self.control.fields.start==1),self.sticky.eq(0)))
            
        
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
            i_K = self.K_sig,
            i_start = self.control.fields.start,
            o_busy = self.busy_sig,
            i_in_valid = self.in_valid,
            i_out_ready = self.out_ready,
            o_in_ready = self.in_ready,
            o_out_valid = self.out_valid,
            o_done = self.done_sig,
            i_a_in_TOP = self.a_in_TOP,
            i_b_in_TOP = self.b_in_TOP,
            o_res_out_TOP = self.res_out_TOP
        )