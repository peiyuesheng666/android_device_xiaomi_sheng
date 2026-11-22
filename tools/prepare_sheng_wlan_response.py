#!/usr/bin/env python3
"""Preserve WLAN include flags using content-addressed compiler response files.

Only the prepared, device-owned module source is changed. The content-addressed
filename keeps Kbuild command-change detection sensitive to every include flag
and its order, without passing the entire include list through /bin/sh -c.
"""
import argparse
import hashlib
import json
from pathlib import Path

RELATIVE = Path('vendor/qcom/opensource/wlan/qcacld-3.0/Kbuild')
ANCHOR = 'ccflags-y += $(INCS)\n'
REPLACEMENT = '''# Keep the complete ordered include list out of the shell command argument.
# A content-addressed name preserves Kbuild command-change detection. GNU make
# writes the expanded flags directly; no large shell argument is needed here.
sheng_wlan_inc_tmp := $(shell mktemp "$(obj)/.sheng-wlan-includes.XXXXXX")
ifeq ($(sheng_wlan_inc_tmp),)
$(error Cannot create sheng WLAN include response file)
endif
$(file >$(sheng_wlan_inc_tmp),$(INCS))
sheng_wlan_inc_digest := $(word 1,$(shell sha256sum "$(sheng_wlan_inc_tmp)"))
ifeq ($(sheng_wlan_inc_digest),)
$(error Cannot hash sheng WLAN include response file)
endif
sheng_wlan_inc_rsp := $(obj)/.sheng-wlan-includes-$(sheng_wlan_inc_digest).rsp
sheng_wlan_inc_saved := $(shell if test -e "$(sheng_wlan_inc_rsp)"; then \\
    cmp -s "$(sheng_wlan_inc_tmp)" "$(sheng_wlan_inc_rsp)" && \\
    rm -f "$(sheng_wlan_inc_tmp)"; else \\
    mv "$(sheng_wlan_inc_tmp)" "$(sheng_wlan_inc_rsp)"; fi && echo OK)
ifneq ($(sheng_wlan_inc_saved),OK)
$(error Cannot preserve sheng WLAN include response file)
endif
ccflags-y += @$(sheng_wlan_inc_rsp)
'''


def patched(text):
    if text.count(REPLACEMENT) == 1 and ANCHOR not in text:
        return text
    if text.count(ANCHOR) != 1 or 'sheng_wlan_inc_rsp' in text:
        raise ValueError('Unknown or partially modified WLAN include recipe')
    return text.replace(ANCHOR, REPLACEMENT, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve(strict=True)
    path = root / RELATIVE
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Expected prepared WLAN Kbuild inside source root')
    before = path.read_text()
    after = patched(before)
    row = dict(path=str(RELATIVE), changed=before != after,
               before_sha256=hashlib.sha256(before.encode()).hexdigest(),
               after_sha256=hashlib.sha256(after.encode()).hexdigest(),
               ordered_include_flags_preserved=True,
               content_addressed_command_tracking=True,
               runtime_verified=False)
    if before != after:
        path.write_text(after)
    (root / '.sheng-wlan-include-response.json').write_text(json.dumps(row, indent=2) + '\n')
    print(json.dumps(row, indent=2))


if __name__ == '__main__':
    main()
