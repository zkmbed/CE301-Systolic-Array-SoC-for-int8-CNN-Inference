N ?= 4
export N

SIM ?= icarus
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(PWD)/../../rtl/mac_pe.v $(PWD)/../../rtl/systolic_array.v $(PWD)/../../rtl/skew.v $(PWD)/skew_array_top.v
COCOTB_TOPLEVEL = skew_array_top
COCOTB_TEST_MODULES = test_skew_array
COMPILE_ARGS += -P$(COCOTB_TOPLEVEL).N=$(N)
SIM_BUILD = sim_build_N$(N)

include $(shell cocotb-config --makefiles)/Makefile.sim
