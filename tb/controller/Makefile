SIM ?= icarus
TOPLEVEL_LANG = verilog
N ?= 8
KMAX ?= 1024
export N
export KMAX
VERILOG_SOURCES = $(PWD)/../../rtl/controller.v
COCOTB_TOPLEVEL = controller
COCOTB_TEST_MODULES = test_controller
COMPILE_ARGS += -Pcontroller.N=$(N) -Pcontroller.K_max=$(KMAX)
SIM_BUILD = sim_build_N$(N)_K$(KMAX)
include $(shell cocotb-config --makefiles)/Makefile.sim
