# QTI bootstrap candidate, 2026-11-13

2026-11-14 source iteration: global Soong analysis has been stopped at the
user's request. Continue source fixes and isolated checks; qualify the normal
production pair during the combined integration stage. No build is active.
The source-sync wrapper now accepts an explicit, qualified QTI selection and
reapplies it after default extraction while keeping media source verification.
Twelve local checks passed in
`reports/device/20261114-source-iteration/qti-selection-checks-ivpv8wyk/receipt.json`.
They cover early rejection of incomplete/unqualified selection, actual output
lock ownership and extraction/reselection formatting. No production candidate
was selected, built or installed by those checks. E: remains forbidden for swap.

The new candidate creates the current 288-byte HIDL ComponentStore wrapper,
enumerates all 19 OEM components, creates/releases all 19 C2 interfaces plus
the actual AVC decoder and HEVC encoder components, and exits normally under
the original seccomp policies. It is an isolated,
uninstalled candidate. A separate extension now decodes eight AVC frames;
every YUV byte matches an independent software reference, including EOS and
normal stop/detach/release/exit. Normal Soong production-pair qualification,
HAL installation, boot behavior, application video, HDR and DRM remain pending.

The frame receipt is `reports/device/20261114-qti-frames/runtime-r7/runtime.json`,
using fixture-r1 and the separately compiled qti-frames-20261114-r6 build.
Each frame is 24,576 bytes; all eight differing-byte counts and error metrics
are zero. The original seccomp policies remain enforced. No HAL was registered,
partition flashed or system service restarted; device baseline and existing
QTI/Dolby process identities matched before/after. This receipt qualifies the
diagnostic bridge, not the normally built production pair or historical boot crash.

The tablet stayed on ca10ede3 A, kernel 5.15.220-gf9ca2b71f672 and SELinux
Enforcing. QTI PID 3313 and Dolby PIDs 1378/1412 remained unchanged.
No HAL was registered, system service restarted or partition flashed.

## Separate loading groups

The original source main directly depends on VNDK. At executable startup its
dependencies join the global lookup group; changing dependency order cannot
give each OEM field vector its own storage.

qti_bootstrap.cpp has only minijail, log and C runtime dependencies. After
installing the original sandbox it opens each provider as an independent
RTLD_LOCAL root, then opens the source service payload. Each new root precedes
its dependencies in its local relocation lookup group. The payload uses the
reviewed OEM factory bridge and allocates ComponentStore from current headers.
It verifies no_new_privs=1 and seccomp filter mode=2 before initialization.
The bootstrap rejects C2 providers already loaded at startup.

The first experiment put V4L2 last. Its C2Rect field relocation pointed into
colorconvert, and natural exit failed. Moving V4L2 before colorconvert gave all
**318 actual GOT relocations across seven libraries** their own object addresses,
including after factory use and store release. The external caller observed
exit code 0. This checks relocation slots rather than treating dlsym's
definition lookup as proof of binding.

## Plugin lifetime

The first real-payload experiment created the wrapper successfully but failed
at exit. Sandboxed strace records SIGSEGV at 0x7086ee8c58 after unmapping
libqcodec2_imgtxrfilter.so at 0x7086ea1000. Offset 0x47c58 is in that plugin's
.data.rel.ro, so later cleanup accesses an unloaded plugin's data tables.
The image and CVP plugins are both unloaded in this cleanup sequence.

The bootstrap keeps ordinary dlopen references to these two plugins and the
seven providers for the process lifetime. The registry can release its own
references while code and tables used by remaining C2 objects stay mapped.
Ordinary global finalizers still run. No finalizer is intercepted or removed,
no module uses RTLD_NODELETE, and no early process-exit function is substituted.
Both the wrapper probe and the expanded interface probe now exit with code 0.

## Evidence and limits

Directories below are under workspace reports/device/20261113-full-product.

| Directory | Result |
| --- | --- |
| qti-load-groups | Wrong V4L2 order; binding mismatch and exit 159. Rejected. |
| qti-load-groups-r3 | All 318 bindings match; 19 components; natural exit 0. |
| qti-bootstrap-r1 | Wrapper status 0 and 19 components; exit SIGSEGV/SIGSYS. Rejected. exit.strace records the unmapped plugin access. |
| qti-bootstrap-r2 | Two additional plugin references; wrapper/status/list/release and natural exit 0. |
| qti-bootstrap-r3 | Sandbox mode confirmed; wrapper 288/status 0; all 19 interfaces created with C2_OK and released; natural exit 0. Eleven ELF hashes and both policy hashes match the device. |
| qti-bootstrap-r4 | All r3 wrapper/interface checks plus actual c2.qti.avc.decoder and c2.qti.hevc.encoder construction, intf/name access and release; both C2_OK and natural exit 0. The same device inputs/policies and QTI/Dolby service PIDs match before/after. |

The r4 directly compiled bootstrap is SHA-256
ad6cb37e6e7dc8f876f7332273e618a606b79bfecf331a345cddc7ba7f82ff44;
its payload is
679b1c8037f9d753a443f150b30db834c770a3960fdb3f8b485034eab55c7afa.
Commands, source hashes and output identities are retained in build.json and
commands.json. These builds reuse recorded normal compiler/linker flags and
matching platform libraries, with separate outputs. They are not normal Soong
module-build receipts. Both new Soong modules remain installable:false.
The current full product build retains the OEM QTI installer.

These experiments do not establish the historical QTI boot-exit cause.
The Dolby HEVC DEAD_OBJECT boot problem remains unresolved until the qualified
source service is integrated and tested through that actual path. Interface
creation alone does not prove compressed stream processing or protected playback.
The r4 extension allocates the actual vendor components without queuing frames;
the new frame diagnostic starts AVC, queues compressed access units, receives
all eight decoded frames and EOS, and compares the actual output bytes.
Unsupported CPU-read usage is optional, matching CCodecBufferChannel;
FLAG_INCOMPLETE input-consumed callbacks are accepted while complete output
and EOS remain mandatory. Protected content is still untested.
Normal-pair installation qualification now also requires this component
creation/release check; the previous interface-only receipt is insufficient.
The probes run in the temporary su domain rather than the final mediacodec
service domain.

The inspected bionic revision is ff3bb041547924ac1a7504e4b3bd3ea18169ca2f,
particularly find_libraries and global/local lookup groups. frameworks/av
remains 1c5914737a1a89d0c5b3e52e8289019eab3f8cbf. Refreshed piano, nuwa and
sm8550-common references and the OEM factory ABI are recorded in
[README-qti.md](../interfaces/compat/codec2/README-qti.md).
No public repository or OEM ELF bytes were changed.

The previous full build has completed and its baseline is retained separately.
The later frozen stylus/media build attempts are historical; the latest analysis
was cancelled by the user to prioritize source repair. Normal qualification of
the current production pair remains pending. During integration, verify the
successful normal receipt, exact source mirror, dependencies and newly built
pair with the isolated probe before changing installer selection. Keep the old
single-main candidate excluded.

## Installer preparation

The retired `postprocess_vendor.py --qti-candidate` selection now fails before
writing any output. Default extraction keeps the OEM service. It also removes
the marked bootstrap/payload installer declarations if a development checkout
previously selected them, without leaving the companion payload installed.

`record_sheng_qti_bootstrap_build.py` records the actual outputs and compiler/
linker commands after a successful dedicated normal build of both new modules.
It checks the synchronized five source inputs, completed source/public-source
audits, AArch64, the payload SONAME and the bootstrap's narrow DT_NEEDED list.
The existing runtime runner accepts that receipt and records both output hashes
and the build-receipt hash. Direct compiler experiments remain separate.

`prepare_sheng_qti_bootstrap_installer.py` requires the normal-built pair and
its matching successful isolated runtime receipt. It prepares one binary
installer at the original QTI path, with one separately installed payload at
`/vendor/lib64/libsheng_qti_codec2_service.so`. The payload and nine providers
are `required` modules rather than bootstrap link dependencies. This preserves
the local dlopen loading groups. Original service/module identity, RC, UID and
OEM input bytes are retained. `--apply` takes the build output lock and refuses
to select a candidate while another build owns that lock. The source preparer
can borrow its enclosing wrapper's FD 9 after validating the file type and
device/inode; closing the duplicate retains the parent's lock. Candidate
qualification occurs before source/vendor writes and again after extraction.

Static checks in `reports/device/20261113-full-product/qti-installer-static`
confirm Blueprint parsing, one installer for each output, idempotent selection,
byte-identical default restoration, rejection of the old candidate and raw
compiler receipts, and refusal to modify the live build. The rendered BP uses
the previous raw receipt as a **formatting fixture only**. It is unqualified
and has not been applied, normally built or installed.

After the source repair batch is substantially ready, the integration sequence is:

1. Mirror media inputs once and normally build both modules with
   `SHENG_INCLUDE_MEDIA_SENSORS=1` using the dedicated module wrapper.
2. Record that successful normal build with the new recorder and test the exact
   pair using `run_sheng_qti_bootstrap_candidate.py`.
3. Prepare and select the installer with the qualified build/runtime receipts.
4. Build the selected service, companion payload and vendor image with
   `SHENG_INCLUDE_MEDIA_SENSORS=1`, `SHENG_QTI_BOOTSTRAP_BUILD` pointing to the
   qualified build directory, and `SHENG_QTI_BOOTSTRAP_RUNTIME` pointing to its
   matching runtime directory. Both directories are mandatory for explicit
   selection. The wrapper mirrors and verifies media sources, restores the OEM
   extraction baseline, then reapplies only that qualified pair under the same
   lock. Check resulting ELF identities, dependencies, labels and unchanged RC.
5. Qualify the actual service domain, startup and video paths before claiming
   the historical boot crash is fixed.

The three bootstrap/payload/header source verification arguments were added
after the four-job full invocation terminated on an explicit Ninja SIGINT.
The earlier full build completed and retained the OEM QTI selection. The recorder
independently checks current source bytes against the normal invocation's
source-sync receipt; neither new QTI module has normal-build artifact or
installed-service qualification yet.

The refreshed reference inputs are retained in
`reports/device/20261114-source-iteration/qti-display-reference-quy2w2fp`:
piano `544cc866793abce19bef661fe4a9fdea1b6d35d2`, nuwa
`8e2b6ca4375919035587115189760eed64f14b8d`, and sm8550-common
`acec5e2cc86d350a498d2f5b621d6e68699c494c`. Their extraction hooks retain
device-specific codec compatibility handling; no reference application or
unrelated board values were imported. The two common-tree filename misses
are recorded as HTTP 404, not successful reference reads.
