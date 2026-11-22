// SPDX-License-Identifier: Apache-2.0
// Real syscalls in a private host mount namespace, NOT Android SELinux acceptance.
#ifdef NDEBUG
#undef NDEBUG
#endif
#include "mount_preserver.h"

#include <sched.h>
#include <cassert>
#include <iostream>

using namespace sheng::remounter;

static int move_count;
static int fail_move_number;
static int FailOneMove(const char* source, const char* target) {
    if (++move_count == fail_move_number) {
        errno = EIO;
        return -1;
    }
    return mount(source, target, nullptr, MS_MOVE, nullptr);
}

static void MakeDirectory(const std::string& path) {
    assert(mkdir(path.c_str(), 0700) == 0);
}

static void WriteFile(const std::string& path, const std::string& text) {
    std::ofstream stream(path);
    stream << text;
    stream.close();
    assert(stream.good());
}

static void ParserTests() {
    std::string path;
    assert(DecodePath("/a\\040b/\\134c", &path) && path == "/a b/\\c");
    assert(!DecodePath("/a\\00", &path));
    assert(!DecodePath("/a\\000", &path));
    assert(!DecodePath("relative", &path));
    std::istringstream valid("45 34 0:1 / /system rw - overlay overlay rw\n"
                             "67 45 0:2 /x /system/a\\040b rw - tmpfs tmpfs rw\n"
                             "68 67 0:3 /x /system/a\\040b/nested rw - tmpfs tmpfs rw\n");
    std::vector<Mount> rows, children;
    assert(ParseMounts(valid, &rows) && SelectChildren(rows, "/system", &children));
    assert(children.size() == 1 && children[0].id == 67 && children[0].point == "/system/a b");
    rows[2].propagation = true;
    assert(!SelectChildren(rows, "/system", &children));
    rows[2].propagation = false;
    rows.push_back(rows[0]);
    assert(!SelectChildren(rows, "/system", &children));
    // Projection of run69ba13d70d766946: /product ext4 mount36 has overlay45
    // as its child at the SAME path. This is a normal stack, not ambiguity.
    rows = {{34, 1, "/", "ext4", false},
            {36, 34, "/product", "ext4", false},
            {45, 36, "/product", "overlay", false},
            {60, 45, "/product/etc/test.rc", "tmpfs", false},
            {61, 60, "/product/etc/test.rc/nested", "tmpfs", false}};
    assert(SelectChildren(rows, "/product", &children));
    assert(children.size() == 1 && children[0].id == 60);
    rows.pop_back();rows.pop_back();
    assert(SelectChildren(rows, "/product", &children) && children.empty());
    rows.push_back({70, 34, "/product", "tmpfs", false});
    assert(!SelectChildren(rows, "/product", &children)); // disconnected alias
    rows.back().parent = 45;
    assert(!SelectChildren(rows, "/product", &children)); // overlay is covered
    rows.pop_back();rows[1].propagation = true;
    assert(!SelectChildren(rows, "/product", &children));
    rows[1].propagation = false;rows[1].parent = 45;
    assert(!SelectChildren(rows, "/product", &children)); // same-path cycle
    rows[1].parent = 34;
    rows.push_back({71, 45, "/product", "overlay", false});
    assert(!SelectChildren(rows, "/product", &children)); // stacked overlays
    rows.pop_back();rows.push_back({72, 45, "/product/file", "tmpfs", false});
    rows.push_back({73, 45, "/product/file", "tmpfs", false});
    assert(!SelectChildren(rows, "/product", &children)); // child alias
    std::istringstream duplicate("1 2 0:1 / /a rw - tmpfs tmpfs rw\n1 2 0:1 / /b rw - tmpfs tmpfs rw\n");
    assert(!ParseMounts(duplicate, &rows));
    std::cout << "parser_escape_topology_negative_cases=passed\n";
}

static void Case(const std::string& base, const std::string& variant) {
    const std::string root = base + "/" + variant;
    const std::string system = root + "/system";
    MakeDirectory(root);
    MakeDirectory(system);
    if (variant == "stacked") {
        assert(mount("partition-lower", system.c_str(), "tmpfs", 0, "size=1m,mode=0700") == 0);
    }
    MakeDirectory(root + "/upper");
    MakeDirectory(root + "/work");
    for (int i = 0; i < 3; ++i) {
        WriteFile(system + "/rc" + std::to_string(i), "lower");
        WriteFile(root + "/source" + std::to_string(i), "magisk-rc-" + std::to_string(i));
    }
    MakeDirectory(system + "/dir");
    MakeDirectory(root + "/dir-source");
    WriteFile(root + "/dir-source/nested", "nested-original");
    WriteFile(root + "/nested-source", "nested-bind");
    std::string options = "lowerdir=" + system + ",upperdir=" + root + "/upper,workdir=" + root + "/work";
    assert(mount("overlay", system.c_str(), "overlay", 0, options.c_str()) == 0);
    if (variant != "empty") {
        for (int i = 0; i < 3; ++i) {
            std::string source = root + "/source" + std::to_string(i);
            std::string target = system + "/rc" + std::to_string(i);
            assert(mount(source.c_str(), target.c_str(), nullptr, MS_BIND, nullptr) == 0);
            if (variant == "deleted") assert(unlink(source.c_str()) == 0);
        }
        if (variant == "nested") {
            assert(mount((root + "/dir-source").c_str(), (system + "/dir").c_str(), nullptr, MS_BIND, nullptr) == 0);
            assert(mount((root + "/nested-source").c_str(), (system + "/dir/nested").c_str(), nullptr, MS_BIND, nullptr) == 0);
        }
        errno = 0;
        assert(umount(system.c_str()) == -1 && errno == EBUSY);
    }
    std::vector<Mount> rows, children;
    assert(ReadMounts(&rows) && SelectChildren(rows, system, &children));
    assert(children.size() == (variant == "empty" ? 0u : variant == "nested" ? 4u : 3u));
    move_count = 0;
    fail_move_number = variant == "partial_move_failure" ? 2 : variant == "restore_retry" ? 4 : -1;
    PreservedChildren saved(FailOneMove);
    std::string error;
    if (variant == "prepare_failure") {
        auto invalid = children;
        invalid.push_back(Mount{99999, children[0].parent, system + "/missing", "tmpfs", false});
        assert(!saved.Stage(invalid, root + "/holder", &error));
        assert(saved.Restore(&error) && saved.Cleanup());
        assert(ReadMounts(&rows) && SelectChildren(rows, system, &children));
        assert(children.size() == 3);
    } else if (variant == "partial_move_failure") {
        assert(!saved.Stage(children, root + "/holder", &error));
        assert(move_count == 2);
        assert(saved.Restore(&error) && saved.Cleanup());
        assert(ReadMounts(&rows) && SelectChildren(rows, system, &children));
        assert(children.size() == 3);
    } else if (variant == "existing_stage") {
        MakeDirectory(root + "/holder");
        WriteFile(root + "/holder/foreign", "do-not-delete");
        assert(!saved.Stage(children, root + "/holder", &error));
        assert(move_count == 0 && saved.Restore(&error) && saved.Cleanup());
        assert(access((root + "/holder/foreign").c_str(), F_OK) == 0);
    } else {
        const bool staged = saved.Stage(children, root + "/holder", &error);
        if (!staged) std::cerr << "case=" << variant << " stage_error=" << error << std::endl;
        assert(staged);
        if (variant == "rollback") {
            int busy = open(system.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
            assert(busy >= 0);
            errno = 0;
            assert(umount(system.c_str()) == -1 && errno == EBUSY);
            assert(close(busy) == 0);
        } else {
            assert(umount(system.c_str()) == 0);
            assert(mount("overlay", system.c_str(), "overlay", MS_RDONLY | MS_NOATIME, options.c_str()) == 0);
        }
        if (variant == "restore_retry") {
            assert(!saved.Restore(&error));
            assert(move_count == 6);  // all three restorations attempted, one failed
        }
        assert(saved.Restore(&error) && saved.Cleanup());
        assert(ReadMounts(&rows) && SelectChildren(rows, system, &children));
    }
    if (variant != "empty") {
        for (int i = 0; i < 3; ++i) {
            std::ifstream stream(system + "/rc" + std::to_string(i));
            std::string text;
            stream >> text;
            assert(text == "magisk-rc-" + std::to_string(i));
        }
    }
    if (variant == "nested") {
        std::ifstream stream(system + "/dir/nested");
        std::string text;
        stream >> text;
        assert(text == "nested-bind");
    }
    std::cout << "case=" << variant << " passed overlay_retained=true\n";
}

int main(int argc, char** argv) {
    std::cout.setf(std::ios::unitbuf);
    assert(argc == 2);
    ParserTests();
    assert(unshare(CLONE_NEWNS) == 0);
    assert(mount(nullptr, "/", nullptr, MS_REC | MS_PRIVATE, nullptr) == 0);
    assert(mount("sheng-preserver-test", argv[1], "tmpfs", 0, "size=16m,mode=0700") == 0);
    for (const std::string variant : {"empty", "three_rc", "stacked", "deleted", "nested", "rollback", "prepare_failure",
                                      "partial_move_failure", "restore_retry", "existing_stage"}) {
        Case(argv[1], variant);
    }
    // Process exit destroys only this child namespace and all test mounts.
    std::cout << "ALL_CASES_PASSED\n";
    return 0;
}
