#!/usr/bin/env python3
"""Compile isolated diagnostic namespace.o, retaining all candidate semantics.

Logs only PID 1 overlay unmount EBUSY while namespace and mount locks are held.
"""
from pathlib import Path
import hashlib
import json
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from storage_guard import require_build_space
K = Path('/root/sheng-pixelos/diagnostics/ksu-rawdump-20261117/vendor-kmi32/k618')
O = (K / 'out-gki').resolve()
C = Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin')
ADDED = '''
		if (retval == -EBUSY && task_pid_nr(current) == 1 &&
		    !strcmp(sb->s_type->name, "overlay")) {
			struct mount *p;
			unsigned int trace_count = 0;

			/* Diagnostic only: all original unmount and security checks remain. */
			for (p = mnt; p && trace_count++ < 64; p = next_mnt(p, mnt))
				pr_err("sheng-umount-busy id=%d parent=%d refs=%d group=%d flags=%x point=%pd4 root=%pd4 type=%s\\n",
				       p->mnt_id, p->mnt_parent->mnt_id, mnt_get_count(p),
				       p->mnt_group_id, p->mnt.mnt_flags,
				       p->mnt_mountpoint, p->mnt.mnt_root,
				       p->mnt.mnt_sb->s_type->name);
		}
'''


def main():
    parent, trial = map(Path, sys.argv[1:])
    require_build_space(trial)
    trial.mkdir(parents=True, exist_ok=False)
    kernel = trial / 'objects/kernel'
    (kernel / 'fs').mkdir(parents=True)
    (trial / 'objects/fs_mgr').symlink_to(parent / 'objects/fs_mgr', target_is_directory=True)
    base = parent / 'objects/kernel/fs/namespace.c'
    source = base.read_text()
    anchor = '\t\t\tumount_tree(mnt, UMOUNT_PROPAGATE|UMOUNT_SYNC);\n\t\t\tretval = 0;\n\t\t}\n'
    assert source.count(anchor) == 1
    candidate = kernel / 'fs/namespace.c'
    candidate.write_text(source.replace(anchor, anchor + ADDED, 1))
    cmd = shlex.split((O / 'fs/.namespace.o.cmd').read_text().split(' := ', 1)[1].split('\n', 1)[0])
    assert cmd[0] == 'clang' and cmd[-1] == str(K / 'ws/common/fs/namespace.c')
    cmd[0] = str(C / 'clang')
    cmd[1] = '-Wp,-MMD,' + str(kernel / 'namespace.d')
    cmd[cmd.index('-o') + 1] = str(kernel / 'namespace.o')
    cmd[-1] = str(candidate)
    p = subprocess.run(cmd, cwd=O, capture_output=True)
    (trial / 'compile.stdout').write_bytes(p.stdout)
    (trial / 'compile.stderr').write_bytes(p.stderr)
    assert p.returncode == 0, p.stderr.decode(errors='replace')
    (trial / 'compile.json').write_text(json.dumps(dict(command=cmd,
        base_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
        diagnostic_only=True, original_sources_unchanged=True), indent=2))
    subprocess.run(['python3', HERE / 'link_trial.py', trial], check=True)


if __name__ == '__main__':
    main()
