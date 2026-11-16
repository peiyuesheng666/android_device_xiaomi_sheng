// SPDX-License-Identifier: Apache-2.0
#include "PenLeaseJournal.h"
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace sheng::stylus {
PenLeaseJournal::PenLeaseJournal(const std::string& directory) {
    directory_ = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (directory_ < 0) return;
    struct stat state{};
    const int result = fstatat(directory_, "lease", &state, AT_SYMLINK_NOFOLLOW);
    blocked_ = result == 0 || errno != ENOENT;
}
PenLeaseJournal::~PenLeaseJournal() { if (directory_ >= 0) close(directory_); }
bool PenLeaseJournal::begin() {
    if (blocked_ || owned_ || directory_ < 0) return false;
    const int fd = openat(directory_, "lease", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) { blocked_ = true; return false; }
    constexpr char intent[] = "sheng-stylus-connection-intent-v1\n";
    const bool saved = write(fd, intent, sizeof(intent) - 1) == static_cast<ssize_t>(sizeof(intent) - 1)
            && fsync(fd) == 0 && fsync(directory_) == 0;
    close(fd);
    owned_ = saved;
    blocked_ = !saved;
    // A failed commit is also ambiguous; never remove the marker on that path.
    return saved;
}
bool PenLeaseJournal::finish() {
    if (!owned_) return !blocked_;
    if (unlinkat(directory_, "lease", 0) != 0 || fsync(directory_) != 0) {
        blocked_ = true; return false;
    }
    owned_ = false;
    return true;
}
}  // namespace sheng::stylus
