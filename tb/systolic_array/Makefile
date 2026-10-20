# Run with: make N=2   (or N=4, N=8). Default N=4.
N ?= 4
export N

SIM ?= icarus
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(PWD)/../../rtl/pe.v $(PWD)/../../rtl/systolic_array.v
COCOTB_TOPLEVEL = systolic_array
COCOTB_TEST_MODULES = test_systolic_array
COMPILE_ARGS += -P$(COCOTB_TOPLEVEL).N=$(N)
SIM_BUILD = sim_build_N$(N)

include $(shell cocotb-config --makefiles)/Makefile.sim
