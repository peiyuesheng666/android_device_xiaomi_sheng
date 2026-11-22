# Device build mirror guard, 2026-11-11

The installed framework defaults and WSL overlay source have regressed to 60 Hz
while the authoritative Windows overlay source remains at 144 Hz. Public source
audits pass because device/xiaomi/sheng is intentionally outside their scope.
The face r44 build/package scope also includes the framework overlay, allowing
unrelated device source drift to reach a subsequent image.

verify_device_source_mirror.py compares file bytes and symbolic-link targets for
Git-inventoried device build inputs, including non-ignored new files, against the
chosen ROM mirror. Missing inputs fail. It writes a hash receipt and refuses
the build on differences; it does not synchronize or edit sources. Documentation
and local tools/caches are excluded. The independent upstream source audit still
checks all public repositories. This guard does not check extra untracked ROM
files or establish complete output dependency coverage.

For this Windows/WSL workspace, run the local helper with:

```sh
SHENG_SOURCE_WORKSPACE=/path/to/workspace bash device/xiaomi/sheng/tools/build_hardware.sh TARGETS...
```

For a scoped build, SHENG_SOURCE_SCOPE accepts whitespace-separated paths
relative to device/xiaomi/sheng; the receipt records that limited scope. Omit it
to compare all inventoried build inputs. Do not describe a scoped pass as a
whole-tree pass. Kernel 6.18 experiments in the user's other chat are excluded
from this display batch's synchronization and scoped guard.

build_hardware.sh checks the mirror before dependency staging and compilation
when this variable is supplied. Ordinary builds from one authoritative checkout
can omit it. A scoped build must additionally verify the compiled resources and
the exact files entering a package. The r47 batch will retain a snapshot of WSL
differences before synchronization and prove the guard rejects those differences.
