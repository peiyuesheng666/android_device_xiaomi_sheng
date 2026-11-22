#!/usr/bin/env python3
"""Link an instrumentation-only stock remounter in a new isolated directory.

No source/output replacement, packaging, mounting or device operations.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from build_sheng_fstab_variants import blocks, statements
from storage_guard import require_build_space

TRACE = r'''
static void sheng_trace_mounts() {
    for (const char* path : {"/proc/self/mountinfo", "/proc/self/maps"}) {
        std::string text;
        if (!android::base::ReadFileToString(path, &text)) {
            PLOG(ERROR) << "sheng-remounter-trace read " << path;
            continue;
        }
        for (const auto& line : android::base::Split(text, "\n")) {
            if (!line.empty()) LOG(INFO) << "sheng-remounter-trace " << path << " " << line;
        }
    }
    DIR* dir = opendir("/proc/self/fd");
    if (!dir) {
        PLOG(ERROR) << "sheng-remounter-trace opendir fd";
        return;
    }
    while (auto* ent = readdir(dir)) {
        if (ent->d_name[0] == '.') continue;
        std::string path = std::string("/proc/self/fd/") + ent->d_name;
        char target[4096];
        ssize_t n = readlink(path.c_str(), target, sizeof(target) - 1);
        if (n < 0) continue;
        target[n] = 0;
        LOG(INFO) << "sheng-remounter-trace fd " << ent->d_name << " -> " << target;
    }
    closedir(dir);
}
'''


def main():
    rom, out = map(Path, sys.argv[1:])
    require_build_space(out)
    out.mkdir(parents=True, exist_ok=False)
    source = rom / 'system/core/overlay_remounter/overlay_remounter.cpp'
    original = source.read_text()
    assert original.count('    // Remount ouerlayfs') == 1
    modified = original.replace('#include <unistd.h>', '#include <unistd.h>\n#include <dirent.h>')
    modified = modified.replace('static bool umount_retry(', TRACE + '\nstatic bool umount_retry(', 1)
    modified = modified.replace('    // Remount ouerlayfs', '    sheng_trace_mounts();\n\n    // Remount ouerlayfs', 1)
    candidate = out / 'overlay_remounter.cpp'
    candidate.write_text(modified)
    soong = rom / 'out-clean-ota-20261116/soong'
    main_graph = soong / 'build.custom_sheng.ninja'
    definitions = [s for s in statements(main_graph) if s.startswith('g.') and ' = ' in s]
    rules = [b for b in blocks(main_graph) if b[0] in ('rule g.cc.cc', 'rule g.cc.ld')]
    edges = [b for b in blocks(soong / 'build.custom_sheng.8.ninja')
             if b[0].startswith('build ') and '/overlay_remounter/' in b[0]
             and (': g.cc.cc ' in b[0] or ': g.cc.ld ' in b[0])]
    assert len(rules) == len(edges) == 2
    cc = next(b for b in edges if ': g.cc.cc ' in b[0])
    ld = next(b for b in edges if ': g.cc.ld ' in b[0])
    obj = cc[0][6:].split(': ', 1)[0]
    binary = ld[0][6:].split(': ', 1)[0]
    new_obj, new_bin = out / 'trace.o', out / 'overlay_remounter.unstripped'
    cc = [s.replace(obj, str(new_obj)).replace(str(source.relative_to(rom)), str(candidate)) for s in cc]
    ld = [s.replace(binary, str(new_bin)).replace(obj, str(new_obj)) for s in ld]
    graph = out / 'trace.ninja'
    graph.write_text('\n'.join(definitions + ['builddir = ' + str(out)] +
                               ['\n'.join(b) for b in rules + [cc, ld]]) + '\n')
    p = subprocess.run([rom / 'prebuilts/build-tools/linux-x86/bin/ninja', '-f', graph,
                        '-j1', '-v', new_bin], cwd=rom, capture_output=True)
    (out / 'build.stdout').write_bytes(p.stdout)
    (out / 'build.stderr').write_bytes(p.stderr)
    assert p.returncode == 0, p.stderr.decode(errors='replace')
    subprocess.run([rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-strip',
                    '--strip-debug', '-o', out / 'overlay_remounter', new_bin], check=True)
    assert source.read_text() == original
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    receipt = dict(source_sha256=sha(source), candidate_sha256=sha(candidate),
                   binary_sha256=sha(out / 'overlay_remounter'), instrumentation_only=True,
                   original_source_unchanged=True, device_access=False)
    (out / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
