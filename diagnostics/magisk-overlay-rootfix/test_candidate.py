#!/usr/bin/env python3
"""Test isolated copies of the actual fs_mgr function, never the product tree.

Linux root required. All mounts run in a private child namespace. SELinux context
success/error injection is NOT an Android pre-policy SELinux reproduction.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent

HARNESS = r'''
#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/xattr.h>
#include <unistd.h>
using namespace std::literals;
std::string kMoveMountTempDir;
std::string mode;
std::string foreign_slot;
int moves = 0;
namespace android::base {
bool StartsWith(const std::string& s, const std::string& p) {
    return s.compare(0, p.size(), p) == 0;
}
}
#define PERROR std::cerr
#define LOG(x) std::cerr
struct FstabEntry {std::string mount_point; std::string options;};
struct mount_info {std::string mount_point; bool shared_flag;};
struct AutoSetFsCreateCon {
    bool Set(const std::string&) {return mode != "setcontext-error";}
    bool Restore() {return true;}
};
int getfilecon(const char* path, char** out) {
    if (mode == "permission-error") {errno = EACCES; return -1;}
    if (mode == "unsupported") {errno = EOPNOTSUPP; return -1;}
    if (mode == "labeled" || mode == "setcontext-error") {
        *out = strdup("u:object_r:tmpfs:s0"); return strlen(*out) + 1;
    }
    auto size = getxattr(path, "security.selinux", nullptr, 0);
    if (size < 0) return -1;
    *out = static_cast<char*>(calloc(size + 1, 1));
    if (getxattr(path, "security.selinux", *out, size) < 0) {
        free(*out); *out = nullptr; return -1;
    }
    return size + 1;
}
void freecon(char* p) {free(p);}
std::string fs_mgr_get_context(const std::string& p) {
    char* value = nullptr;
    if (getfilecon(p.c_str(), &value) < 0) return {};
    std::string out(value); freecon(value); return out;
}
std::string fs_mgr_mount_point(const std::string& p) {return p;}
std::string fs_mgr_get_overlayfs_options(const FstabEntry& e) {return e.options;}
bool fs_mgr_overlayfs_set_shared_mount(const std::string& p, bool shared) {
    return mount(nullptr, p.c_str(), nullptr, shared ? MS_SHARED : MS_PRIVATE, nullptr) == 0;
}
bool fs_mgr_overlayfs_move_mount(const std::string& s, const std::string& d) {
    ++moves;
    if (mode == "second-move-error" && moves == 2) {errno = EIO; return false;}
    return mount(s.c_str(), d.c_str(), nullptr, MS_MOVE, nullptr) == 0;
}
bool fs_mgr_overlayfs_mount(const std::string& p, const std::string& options) {
    if (mode == "overlay-error") {errno = EIO; return false;}
    return mount("overlay", p.c_str(), "overlay", MS_RDONLY | MS_NOATIME, options.c_str()) == 0;
}
std::vector<mount_info> ReadMountinfoFromFile(const std::string& p) {
    if (mode == "no-mountinfo") return {};
    std::vector<mount_info> out; std::ifstream stream(p); std::string line;
    while (std::getline(stream, line)) {
        std::istringstream words(line); std::string word; mount_info entry;
        for (int i = 0; i < 5; ++i) words >> word;
        entry.mount_point = word; entry.shared_flag = false;
        while (words >> word && word != "-") {
            if (word.compare(0, 7, "shared:") == 0) entry.shared_flag = true;
        }
        out.push_back(entry);
    }
    return out;
}
int test_mkstemp(char* name) {
    if (mode == "mkstemp-error") {
        foreign_slot = name;
        std::ofstream(foreign_slot) << "FOREIGN_FILE";
        errno = EACCES;
        return -1;
    }
    return mkstemp(name);
}
#define mkstemp test_mkstemp
// BEGIN ACTUAL SOURCE FUNCTION
@FUNCTION@
// END ACTUAL SOURCE FUNCTION
#undef mkstemp
void require(bool ok, const char* what) {
    if (!ok) {std::cerr << "FAILED: " << what << " errno=" << errno << '\n'; exit(1);}
}
void put(const std::string& p, const std::string& value) {std::ofstream(p) << value;}
std::string read(const std::string& p) {
    std::ifstream f(p); return {std::istreambuf_iterator<char>(f), {}};
}
int main(int argc, char** argv) {
    require(argc == 5, "arguments");
    std::string root = argv[1], kind = argv[2]; mode = argv[3];
    bool fixed = std::string(argv[4]) == "fixed";
    require(mount("tmpfs", root.c_str(), "tmpfs", 0, "size=8m") == 0, "private tmpfs");
    auto dir = [](const std::string& p) {std::filesystem::create_directories(p);};
    auto system = root + "/system", target = system + "/bin/init";
    dir(system + "/bin"); dir(root + "/upper"); dir(root + "/work");
    kMoveMountTempDir = root + "/holding"; dir(kMoveMountTempDir);
    require(mount("tmpfs", kMoveMountTempDir.c_str(), "tmpfs", 0, "size=1m") == 0, "holding mount");
    require(fs_mgr_overlayfs_set_shared_mount(kMoveMountTempDir, mode == "shared-holding"), "holding propagation");
    auto source = root + "/source";
    if (kind == "directory") {dir(target); dir(source); put(target + "/value", "ANDROID_INIT"); put(source + "/value", "MAGISK_INIT");}
    else {put(target, "ANDROID_INIT"); put(source, "MAGISK_INIT");}
    require(mount(source.c_str(), target.c_str(), nullptr, MS_BIND, nullptr) == 0, "bind");
    if (kind == "deleted-file") require(unlink(source.c_str()) == 0, "unlink source");
    struct stat before, after; require(stat(target.c_str(), &before) == 0, "initial inode");
    if (mode == "second-move-error") {
        put(system + "/bin/second", "ANDROID_SECOND"); put(root + "/second-source", "MAGISK_SECOND");
        require(mount((root + "/second-source").c_str(), (system + "/bin/second").c_str(), nullptr, MS_BIND, nullptr) == 0, "second bind");
    }
    FstabEntry entry{system, "lowerdir=" + system + ",upperdir=" + root + "/upper,workdir=" + root + "/work,userxattr"};
    bool result = fs_mgr_overlayfs_mount_one(entry);
    require(stat(target.c_str(), &after) == 0, "final inode");
    auto visible = read(kind == "directory" ? target + "/value" : target);
    bool overlay = false;
    std::ifstream mounts("/proc/self/mountinfo"); std::string line;
    while (std::getline(mounts, line)) {
        if (line.find(" " + system + " ") != std::string::npos && line.find(" - overlay ") != std::string::npos) overlay = true;
    }
    if (fixed) {
        bool reject = kind == "deleted-file" || mode == "permission-error" || mode == "setcontext-error" || mode == "overlay-error" || mode == "second-move-error" || mode == "no-mountinfo" || mode == "shared-holding" || mode == "mkstemp-error";
        require(result != reject, "return status"); require(overlay != reject, "overlay state");
        require(visible == "MAGISK_INIT", "bind remains visible"); require(before.st_ino == after.st_ino, "same inode");
        if (mode == "second-move-error") require(read(system + "/bin/second") == "MAGISK_SECOND", "second bind intact");
        if (mode == "mkstemp-error") require(read(foreign_slot) == "FOREIGN_FILE", "colliding unowned name retained");
    } else {require(overlay && visible == "ANDROID_INIT", "original hides bind");}
    std::cout << "{\"passed\":true,\"function_return\":" << (result ? "true" : "false") << ",\"overlay_mounted\":" << (overlay ? "true" : "false") << ",\"same_inode\":" << (before.st_ino == after.st_ino ? "true" : "false") << ",\"visible\":\"" << visible << "\"}\n";
}
'''


def function(source):
    start = source.index('static bool fs_mgr_overlayfs_mount_one(')
    end = source.index('\n// Mount kScratchMountPoint', start)
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fs-mgr', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0
    assert not args.out.exists()
    namespace = os.readlink('/proc/self/ns/mnt')
    mountinfo = Path('/proc/self/mountinfo').read_bytes()
    source = args.fs_mgr.read_bytes()
    metadata = json.loads((HERE/'candidate-base.json').read_text())
    assert hashlib.sha256(source).hexdigest() == metadata['fs_mgr_base_sha256']
    cases = [('file', 'actual-enodata'), ('directory', 'actual-enodata'),
             ('file', 'unsupported'), ('file', 'labeled'),
             ('file', 'permission-error'), ('file', 'setcontext-error'),
             ('file', 'overlay-error'), ('file', 'second-move-error'),
             ('file', 'no-mountinfo'), ('file', 'shared-holding'),
             ('file', 'mkstemp-error'),
             ('deleted-file', 'actual-enodata')]
    results = []
    with tempfile.TemporaryDirectory(prefix='sheng-overlay-rootfix-', dir='/tmp') as tmp:
        root = Path(tmp)
        original = root/'fs_mgr_overlayfs_mount.cpp'
        original.write_bytes(source)
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(HERE/'fs_mgr-preserve-file-submounts.patch')], cwd=root, check=True, capture_output=True)
        candidate = original.read_bytes()
        assert hashlib.sha256(candidate).hexdigest() == metadata['fs_mgr_candidate_sha256']
        for version, content in [('original', source), ('fixed', candidate)]:
            cpp = root/(version + '.cpp'); binary = root/version
            cpp.write_text(HARNESS.replace('@FUNCTION@', function(content.decode())))
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-O1', '-g', '-fsanitize=undefined', str(cpp), '-o', str(binary)], check=True, capture_output=True)
            selected = cases if version == 'fixed' else [('file', 'actual-enodata'), ('file', 'labeled')]
            for i, (kind, mode) in enumerate(selected):
                fixture = root/(version + '-fixture-' + str(i)); fixture.mkdir()
                cmd = ['unshare', '--mount', '--propagation', 'private', str(binary), str(fixture), kind, mode, version]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                assert proc.returncode == 0, (version, kind, mode, proc.stdout, proc.stderr)
                assert not any(fixture.iterdir()), 'Mount leaked into caller namespace'
                results.append(dict(version=version, kind=kind, context_mode=mode, **json.loads(proc.stdout)))
    assert os.readlink('/proc/self/ns/mnt') == namespace
    assert Path('/proc/self/mountinfo').read_bytes() == mountinfo
    assert args.fs_mgr.read_bytes() == source
    report = dict(results=results, caller_mount_table_unchanged=True,
                  original_source_sha256=hashlib.sha256(source).hexdigest(),
                  candidate_source_sha256=hashlib.sha256(candidate).hexdigest(),
                  original_source_unchanged=True, context_calls_are_test_shims=True,
                  actual_android_prepolicy_selinux_reproduced=False,
                  kernel_candidate_running=False, android_build=False,
                  flash=False, root_cause_fix_complete=False)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
