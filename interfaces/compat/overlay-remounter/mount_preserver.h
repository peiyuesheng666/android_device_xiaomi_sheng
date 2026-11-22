// SPDX-License-Identifier: Apache-2.0
// Preserve live bind mounts across real overlay teardown/recreation.
// No lazy unmount, copied payloads, relabeling, or SELinux policy bypass.
#pragma once

#include <fcntl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>

#include <charconv>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace sheng::remounter {

struct Mount {
    int id = 0;
    int parent = 0;
    std::string point;
    std::string type;
    bool propagation = false;
};

inline bool DecodePath(const std::string& input, std::string* output) {
    output->clear();
    for (size_t i = 0; i < input.size(); ++i) {
        if (input[i] != '\\') {
            output->push_back(input[i]);
            continue;
        }
        if (i + 3 >= input.size()) return false;
        int value = 0;
        for (size_t j = 1; j <= 3; ++j) {
            if (input[i + j] < '0' || input[i + j] > '7') return false;
            value = value * 8 + input[i + j] - '0';
        }
        // mountinfo escapes whitespace and backslash, never NUL or slash.
        if (value != ' ' && value != '\t' && value != '\n' && value != '\\') return false;
        output->push_back(static_cast<char>(value));
        i += 3;
    }
    return !output->empty() && output->front() == '/';
}

inline bool ParseMounts(std::istream& input, std::vector<Mount>* output) {
    output->clear();
    std::set<int> ids;
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream stream(line);
        std::vector<std::string> fields;
        for (std::string field; stream >> field;) fields.push_back(field);
        if (fields.size() < 10) return false;
        size_t separator = 6;
        while (separator < fields.size() && fields[separator] != "-") ++separator;
        if (separator + 4 != fields.size()) return false;
        Mount row;
        auto number = [](const std::string& text, int* value) {
            auto result = std::from_chars(text.data(), text.data() + text.size(), *value);
            return result.ec == std::errc() && result.ptr == text.data() + text.size() && *value > 0;
        };
        if (!number(fields[0], &row.id) || !number(fields[1], &row.parent) ||
            !ids.insert(row.id).second || !DecodePath(fields[4], &row.point)) return false;
        row.type = fields[separator + 1];
        for (size_t i = 6; i < separator; ++i) {
            if (fields[i].rfind("shared:", 0) == 0 || fields[i].rfind("master:", 0) == 0 ||
                fields[i] == "unbindable" || fields[i].rfind("propagate_from:", 0) == 0) row.propagation = true;
        }
        output->push_back(row);
    }
    return !input.bad() && !output->empty();
}

inline bool ReadMounts(std::vector<Mount>* rows) {
    std::ifstream stream("/proc/self/mountinfo");
    return stream.is_open() && ParseMounts(stream, rows);
}

inline bool SelectChildren(const std::vector<Mount>& rows, const std::string& point,
                           std::vector<Mount>* children) {
    children->clear();
    const Mount* parent = nullptr;
    std::set<int> ids;
    for (const auto& row : rows) {
        if (!ids.insert(row.id).second) return false;
        if (row.point != point) continue;
        if (row.propagation) return false;
        if (row.type == "overlay") {
            if (parent) return false;
            parent = &row;
        }
    }
    if (!parent) return false;
    // An ordinary overlay on a separately mounted partition has TWO rows
    // with this path: the lower mount and its overlay child. Accept only a
    // complete, linear same-path ancestor chain below the unique overlay.
    // A covering mount, disconnected duplicate or cycle is still ambiguous.
    std::set<int> lower_chain{parent->id};
    int lower_id = parent->parent;
    while (true) {
        const Mount* lower = nullptr;
        for (const auto& row : rows) {
            if (row.id == lower_id && row.point == point) lower = &row;
        }
        if (!lower) break;
        if (!lower_chain.insert(lower->id).second) return false;
        lower_id = lower->parent;
    }
    for (const auto& row : rows) {
        if (row.point == point && !lower_chain.count(row.id)) return false;
    }
    std::set<std::string> points;
    for (const auto& row : rows) {
        if (row.parent != parent->id) continue;
        if (row.propagation || row.point.rfind(point + "/", 0) != 0 ||
            !points.insert(row.point).second) return false;
        children->push_back(row);
    }
    // Reject propagation anywhere in a preserved subtree, not just its root.
    std::set<int> descendants{parent->id};
    bool changed;
    do {
        changed = false;
        for (const auto& row : rows) {
            if (row.id == parent->id || !descendants.count(row.parent) || descendants.count(row.id)) continue;
            if (row.propagation) return false;
            descendants.insert(row.id);
            changed = true;
        }
    } while (changed);
    return true;
}

class PreservedChildren {
    struct Saved {
        Mount mount;
        std::string holder;
        struct stat original {};
        bool moved = false;
    };
    std::vector<Saved> saved_;
    std::string directory_;
    using Move = int (*)(const char*, const char*);
    static int MoveLive(const char* source, const char* target) {
        return mount(source, target, nullptr, MS_MOVE, nullptr);
    }
    Move move_;

    static bool Identity(const Saved& entry, const std::string& path) {
        struct stat info {};
        if (stat(path.c_str(), &info) || info.st_dev != entry.original.st_dev ||
            info.st_ino != entry.original.st_ino) return false;
        std::vector<Mount> mounts;
        if (!ReadMounts(&mounts)) return false;
        for (const auto& row : mounts) {
            if (row.id == entry.mount.id) return row.point == path;
        }
        return false;
    }

  public:
    explicit PreservedChildren(Move move = MoveLive) : move_(move) {}
    // Directory must be a new, private, correctly labeled staging directory.
    // Caller owns SELinux integration; this helper never changes any labels.
    bool Stage(const std::vector<Mount>& children, const std::string& directory,
               std::string* error) {
        if (!directory_.empty() || !saved_.empty()) {
            *error = "staging transaction reused";
            return false;
        }
        if (children.empty()) return true;
        if (mkdir(directory.c_str(), 0700)) {
            *error = "mkdir staging: " + std::string(strerror(errno));
            return false;
        }
        directory_ = directory;
        // Prepare ALL type-correct targets before moving any live child.
        for (const auto& child : children) {
            Saved entry;
            entry.mount = child;
            entry.holder = directory + "/" + std::to_string(child.id);
            if (lstat(child.point.c_str(), &entry.original) ||
                (!S_ISREG(entry.original.st_mode) && !S_ISDIR(entry.original.st_mode))) {
                *error = "unsupported or inaccessible child: " + child.point;
                return false;
            }
            if (S_ISDIR(entry.original.st_mode)) {
                if (mkdir(entry.holder.c_str(), 0700)) {
                    *error = "mkdir holder: " + std::string(strerror(errno));
                    return false;
                }
            } else {
                int fd = open(entry.holder.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
                if (fd < 0) {
                    *error = "create holder: " + std::string(strerror(errno));
                    return false;
                }
                close(fd);
            }
            saved_.push_back(entry);
        }
        for (auto& entry : saved_) {
            if (!Identity(entry, entry.mount.point)) {
                *error = "source mount identity changed: " + entry.mount.point;
                return false;
            }
            if (move_(entry.mount.point.c_str(), entry.holder.c_str())) {
                *error = "move child: " + entry.mount.point + ": " + strerror(errno);
                return false;
            }
            entry.moved = true;
            if (!Identity(entry, entry.holder)) {
                *error = "staged mount identity differs: " + entry.mount.point;
                return false;
            }
        }
        return true;
    }

    // Also used to roll back partial Stage() or a failed real umount().
    // Try every child even when one restore fails. Never erase a live holder.
    bool Restore(std::string* error) {
        bool ok = true;
        for (auto it = saved_.rbegin(); it != saved_.rend(); ++it) {
            auto& entry = *it;
            if (!entry.moved) continue;
            if (move_(entry.holder.c_str(), entry.mount.point.c_str())) {
                *error += " restore " + entry.mount.point + ": " + strerror(errno);
                ok = false;
                continue;
            }
            entry.moved = false;
            if (!Identity(entry, entry.mount.point)) {
                *error += " restored mount identity differs: " + entry.mount.point;
                ok = false;
            }
        }
        return ok;
    }

    bool Cleanup() {
        bool ok = true;
        for (const auto& entry : saved_) {
            if (entry.moved) { ok = false; continue; }
            if (S_ISDIR(entry.original.st_mode)) ok = rmdir(entry.holder.c_str()) == 0 && ok;
            else ok = unlink(entry.holder.c_str()) == 0 && ok;
        }
        if (!directory_.empty()) ok = rmdir(directory_.c_str()) == 0 && ok;
        return ok;
    }
};

}  // namespace sheng::remounter
