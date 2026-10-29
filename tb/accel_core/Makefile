SIM ?= icarus
TOPLEVEL_LANG = verilog
N ?= 8
KMAX ?= 1024
export N
export KMAX
RTL = $(PWD)/../../rtl
VERILOG_SOURCES = $(RTL)/accel_core.v $(RTL)/controller.v $(RTL)/skew.v $(RTL)/systolic_array.v $(RTL)/mac_pe.v
COCOTB_TOPLEVEL = accel_core
COCOTB_TEST_MODULES = test_accel_core
COMPILE_ARGS += -Paccel_core.N=$(N) -Paccel_core.K_max=$(KMAX)
SIM_BUILD = sim_build_N$(N)_K$(KMAX)
include $(shell cocotb-config --makefiles)/Makefile.sim
