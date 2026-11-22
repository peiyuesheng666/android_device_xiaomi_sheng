/*
 * Copyright (C) 2025 The Android Open Source Project
 * Copyright (C) 2026 sheng device contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <android-base/file.h>
#include <android-base/logging.h>
#include <android-base/strings.h>

#include "mount_preserver.h"

namespace {
bool UnmountRetry(const std::string& point) {
    for (int attempt = 0; attempt < 5; ++attempt) {
        if (umount(point.c_str()) == 0) return true;
        PLOG(ERROR) << "umount FAILED: " << point;
        if (attempt != 4) sleep(1);
    }
    return false;
}
}  // namespace

int main(int /*argc*/, char** argv) {
    android::base::InitLogging(argv, &android::base::KernelLogger);
    LOG(INFO) << "sheng overlay remounter: preserve child mount identities";
    std::string contents;
    CHECK(android::base::ReadFileToString("/proc/mounts", &contents, true));
    for (const auto& line : android::base::Split(contents, "\n")) {
        auto bits = android::base::Split(line, " ");
        if (bits.size() < 4 || bits[2] != "overlay") continue;
        std::string point;
        CHECK(sheng::remounter::DecodePath(bits[1], &point));
        std::vector<sheng::remounter::Mount> mounts, children;
        CHECK(sheng::remounter::ReadMounts(&mounts));
        if (!sheng::remounter::SelectChildren(mounts, point, &children)) {
            // Preserve evidence before PID 1 exits: a missing/aliased target,
            // duplicate mountpoint and propagation are different failures.
            // This diagnostic does not relax any topology or mount checks.
            LOG(ERROR) << "sheng-remounter rejected topology target=" << point
                       << " mount_count=" << mounts.size();
            size_t emitted = 0;
            for (const auto& entry : mounts) {
                if (emitted++ == 256) break;
                LOG(ERROR) << "sheng-remounter topology id=" << entry.id
                           << " parent=" << entry.parent << " point=" << entry.point
                           << " type=" << entry.type << " propagated=" << entry.propagation;
            }
            LOG(FATAL) << "Ambiguous or propagated overlay topology: " << point;
        }
        sheng::remounter::PreservedChildren preserved;
        std::string error;
        if (!preserved.Stage(children, "/second_stage_resources/sheng-remount", &error)) {
            const bool restored = preserved.Restore(&error);
            const bool cleaned = preserved.Cleanup();
            LOG(FATAL) << "Stage children failed: " << error
                       << " restored=" << restored << " cleaned=" << cleaned;
        }
        LOG(INFO) << "sheng-remounter staged " << children.size() << " child mounts of " << point;
        if (!UnmountRetry(point)) {
            const bool restored = preserved.Restore(&error);
            const bool cleaned = preserved.Cleanup();
            LOG(FATAL) << "Overlay unmount failed: " << point << error
                       << " restored=" << restored << " cleaned=" << cleaned;
        }
        std::string options;
        for (const auto& option : android::base::Split(bits[3], ",")) {
            if (option == "ro" || option == "seclabel" || option == "noatime") continue;
            if (!options.empty()) options += ',';
            options += option;
        }
        if (mount("overlay", point.c_str(), "overlay", MS_RDONLY | MS_NOATIME, options.c_str())) {
            // Do not hide recreation errors with lazy detach or a bare lowerdir.
            // Live holders are deliberately retained until the fatal diagnostic.
            PLOG(FATAL) << "Overlay recreation failed; children retained in staging: " << point;
        }
        CHECK(preserved.Restore(&error)) << "Restore children failed: " << error;
        CHECK(preserved.Cleanup()) << "Staging cleanup failed: " << point;
        LOG(INFO) << "sheng-remounter recreated overlay and restored children: " << point;
    }
    const char* args[] = {"/system/bin/init", "second_stage", nullptr};
    execv(args[0], const_cast<char**>(args));
    PLOG(FATAL) << "execv /system/bin/init failed";
    return 1;
}
