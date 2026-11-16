# Called by the ROM's normal external kernel module build/install targets.
sheng_tools := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../../tools)
sheng_python := $(abspath $(sheng_tools)/../../../../prebuilts/build-tools/path/linux-x86/python3)
.PHONY: all modules_install
all:
	$(sheng_python) $(sheng_tools)/build_sheng_source_modules.py --kernel-out $(O)
modules_install:
	$(sheng_python) $(sheng_tools)/build_sheng_source_modules.py --kernel-out $(O) --install-root $(INSTALL_MOD_PATH)
