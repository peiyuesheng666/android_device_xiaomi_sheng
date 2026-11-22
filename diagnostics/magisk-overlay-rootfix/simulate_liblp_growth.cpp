// Offline diagnostic only: read a 1MiB regular-file capture and create a new
// regular-file copy. No partition opener, block-device writes, or mapper APIs.
#include <liblp/builder.h>
#include <liblp/liblp.h>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using namespace android::fs_mgr;

static void Require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}

static uint64_t Number(const char* text) {
    Require(text && *text, "Empty numeric argument");
    uint64_t value = 0;
    for (const char* p = text; *p; ++p) {
        Require(*p >= '0' && *p <= '9', "Invalid unsigned decimal argument");
        const uint64_t digit = *p - '0';
        Require(value <= (std::numeric_limits<uint64_t>::max() - digit) / 10,
                "Numeric overflow");
        value = value * 10 + digit;
    }
    return value;
}

static std::vector<char> ReadCapture(const char* path) {
    android::base::unique_fd fd(open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW));
    struct stat st {};
    Require(fd.get() >= 0 && fstat(fd.get(), &st) == 0 && S_ISREG(st.st_mode),
            "Input must be a regular file, not a symlink or device");
    Require(st.st_size == 1048576, "Require an exact 1MiB super-metadata capture");
    std::vector<char> data(st.st_size);
    size_t done = 0;
    while (done < data.size()) {
        auto n = read(fd.get(), data.data() + done, data.size() - done);
        if (n < 0 && errno == EINTR) continue;
        Require(n > 0, "Read failed or truncated input");
        done += n;
    }
    return data;
}

static void WriteNewRegular(const char* path, const std::vector<char>& data) {
    android::base::unique_fd fd(open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600));
    struct stat st {};
    Require(fd.get() >= 0 && fstat(fd.get(), &st) == 0 && S_ISREG(st.st_mode),
            "Output must be a new regular file; never overwrite an existing path");
    size_t done = 0;
    while (done < data.size()) {
        auto n = write(fd.get(), data.data() + done, data.size() - done);
        if (n < 0 && errno == EINTR) continue;
        Require(n > 0, "Output write failed");
        done += n;
    }
    Require(fsync(fd.get()) == 0, "Output fsync failed");
}

static std::vector<LpMetadataExtent> Extents(const LpMetadata& m, const LpMetadataPartition& p) {
    Require(uint64_t(p.first_extent_index) + p.num_extents <= m.extents.size(), "Extent bounds");
    return {m.extents.begin() + p.first_extent_index,
            m.extents.begin() + p.first_extent_index + p.num_extents};
}

// Compare logical prefix mappings, permitting only harmless coalescing of
// adjacent physical runs. Every original sector must retain its target.
static void VerifyPrefix(const std::vector<LpMetadataExtent>& old,
                         const std::vector<LpMetadataExtent>& now) {
    size_t j = 0;
    uint64_t used = 0;
    for (const auto& a : old) {
        uint64_t done = 0;
        while (done < a.num_sectors) {
            Require(j < now.size(), "Lost original logical extent");
            const auto& b = now[j];
            Require(a.target_type == LP_TARGET_TYPE_LINEAR && b.target_type == LP_TARGET_TYPE_LINEAR,
                    "Only linear physical captures are supported");
            Require(a.target_source == b.target_source && a.target_data + done == b.target_data + used,
                    "An original physical mapping changed");
            const uint64_t count = std::min(a.num_sectors - done, b.num_sectors - used);
            Require(count > 0, "Empty extent");
            done += count;
            used += count;
            if (used == b.num_sectors) { ++j; used = 0; }
        }
    }
}

static void VerifyPreservation(const LpMetadata& old, const LpMetadata& now,
                               const std::string& target, uint64_t requested,
                               bool fastboot_batch_model = false) {
    Require(memcmp(&old.geometry, &now.geometry, sizeof(old.geometry)) == 0, "Geometry changed");
    Require(old.header.flags == now.header.flags && old.header.major_version == now.header.major_version &&
            old.header.minor_version == now.header.minor_version && old.header.header_size == now.header.header_size &&
            memcmp(old.header.reserved, now.header.reserved, sizeof(old.header.reserved)) == 0,
            "Header version, flags or reserved fields changed");
    Require(old.block_devices.size() == now.block_devices.size() && old.groups.size() == now.groups.size() &&
            old.partitions.size() == now.partitions.size(), "Metadata entry counts changed");
    for (size_t i = 0; i < old.block_devices.size(); ++i)
        Require(memcmp(&old.block_devices[i], &now.block_devices[i], sizeof(LpMetadataBlockDevice)) == 0,
                "Block device geometry or alignment changed");
    for (size_t i = 0; i < old.groups.size(); ++i)
        Require(memcmp(&old.groups[i], &now.groups[i], sizeof(LpMetadataPartitionGroup)) == 0,
                "Group flags, name or maximum size changed");
    for (size_t i = 0; i < old.partitions.size(); ++i) {
        const auto& a = old.partitions[i];
        const auto& b = now.partitions[i];
        auto name = GetPartitionName(a);
        const bool flashed_logical = name == "system_b" || name == "system_ext_b" ||
                                     name == "system_dlkm_b" || name == "vendor_dlkm_b";
        const uint32_t expected_attrs = fastboot_batch_model && flashed_logical
                                            ? a.attributes & ~LP_PARTITION_ATTR_UPDATED : a.attributes;
        Require(name == GetPartitionName(b) && expected_attrs == b.attributes && a.group_index == b.group_index,
                "Partition order, attributes or group changed");
        Require(GetPartitionSize(now, b) == (name == target ? requested : GetPartitionSize(old, a)),
                "Unexpected partition size");
        VerifyPrefix(Extents(old, a), Extents(now, b));
    }
}

static void PrintMetadata(const LpMetadata& m) {
    std::cout << "{\"header_flags\":" << m.header.flags << ",\"partitions\":[";
    for (size_t i = 0; i < m.partitions.size(); ++i) {
        const auto& p = m.partitions[i];
        if (i) std::cout << ',';
        std::cout << "{\"name\":\"" << GetPartitionName(p) << "\",\"attributes\":" << p.attributes
                  << ",\"group_index\":" << p.group_index << ",\"bytes\":" << GetPartitionSize(m, p)
                  << ",\"extents\":[";
        const auto extents = Extents(m, p);
        for (size_t j = 0; j < extents.size(); ++j) {
            const auto& e = extents[j];
            if (j) std::cout << ',';
            std::cout << "{\"sectors\":" << e.num_sectors << ",\"type\":" << e.target_type
                      << ",\"source\":" << e.target_source << ",\"physical_sector\":" << e.target_data << '}';
        }
        std::cout << "]}";
    }
    std::cout << "]}";
}

int main(int argc, char** argv) {
    try {
        Require(argc == 6 || argc == 7, "Usage: simulate INPUT_1M NEW_OUTPUT_1M SLOT PARTITION NEW_BYTES [--fastbootd-batch-model]");
        const bool fastboot_batch_model = argc == 7;
        if (fastboot_batch_model)
            Require(std::string(argv[6]) == "--fastbootd-batch-model", "Unknown simulation mode");
        auto bytes = ReadCapture(argv[1]);
        const uint64_t slot = Number(argv[3]);
        Require(slot <= 2, "Unsupported metadata slot");
        auto old = ParseSuperPartition(bytes.data(), bytes.size(), slot);
        Require(old != nullptr, "Unable to validate captured metadata");
        const std::string name(argv[4]);
        Require(name == "vendor_dlkm_b", "Only the qualified vendor_dlkm_b growth is allowed");
        const auto* original = FindPartition(*old, name);
        Require(original != nullptr, "Missing target partition");
        const uint64_t requested = Number(argv[5]);
        const uint64_t prior = GetPartitionSize(*old, *original);
        if (fastboot_batch_model) {
            Require(slot == 1 && old->geometry.metadata_slot_count >= 2, "Batch model requires source slot1 and two boot slots");
            auto slot0 = ParseSuperPartition(bytes.data(), bytes.size(), 0);
            Require(slot0 && ValidateAndSerializeMetadata(*slot0) == ValidateAndSerializeMetadata(*old),
                    "Refuse multi-slot model when current slot0 differs from slot1");
        }
        Require(requested > prior && requested - prior <= 1024 * 1024 && requested % 4096 == 0,
                "Require bounded, aligned growth only");
        auto builder = MetadataBuilder::New(*old);
        Require(builder != nullptr, "Cannot import metadata");
        auto* target = builder->FindPartition(name);
        Require(target && builder->ResizePartition(target, requested), "liblp rejected growth");
        if (fastboot_batch_model) {
            // Match the inspected resize/flash command handlers; this is NOT
            // running fastbootd or assuming that its actual HAL count is proven.
            for (const auto& logical : {"system_b", "system_ext_b", "system_dlkm_b", "vendor_dlkm_b"}) {
                auto* p = builder->FindPartition(logical);
                Require(p != nullptr, "Missing planned logical flash target");
                p->set_attributes(p->attributes() & ~LP_PARTITION_ATTR_UPDATED);
            }
        }
        auto now = builder->Export();
        Require(now != nullptr, "liblp export rejected candidate");
        VerifyPreservation(*old, *now, name, requested, fastboot_batch_model);
        const auto serialized = ValidateAndSerializeMetadata(*now);
        Require(!serialized.empty() && serialized.size() <= old->geometry.metadata_max_size,
                "liblp serialization failed or metadata capacity exceeded");
        const std::vector<uint32_t> written_slots = fastboot_batch_model
                                                       ? std::vector<uint32_t>{0, 1}
                                                       : std::vector<uint32_t>{static_cast<uint32_t>(slot)};
        for (auto written : written_slots) {
            for (auto offset : {GetPrimaryMetadataOffset(old->geometry, written), GetBackupMetadataOffset(old->geometry, written)}) {
                Require(offset >= 0 && uint64_t(offset) + old->geometry.metadata_max_size <= bytes.size(), "Metadata slot out of capture bounds");
                std::fill(bytes.begin() + offset, bytes.begin() + offset + old->geometry.metadata_max_size, 0);
                std::copy(serialized.begin(), serialized.end(), bytes.begin() + offset);
            }
            auto checked = ParseSuperPartition(bytes.data(), bytes.size(), written);
            Require(checked != nullptr, "Serialized metadata failed official readback");
            VerifyPreservation(*old, *checked, name, requested, fastboot_batch_model);
        }
        auto roundtrip = ParseSuperPartition(bytes.data(), bytes.size(), slot);
        Require(roundtrip != nullptr, "Serialized metadata failed official readback");
        VerifyPreservation(*old, *roundtrip, name, requested, fastboot_batch_model);
        WriteNewRegular(argv[2], bytes);
        std::cout << "{\"passed\":true,\"scope\":\"offline liblp allocation only\",\"slot\":" << slot
                  << ",\"prior_bytes\":" << prior << ",\"requested_bytes\":" << requested
                  << ",\"growth_bytes\":" << requested - prior << ",\"serialized_bytes\":" << serialized.size()
                  << ",\"fastbootd_batch_model\":" << (fastboot_batch_model ? "true" : "false")
                  << ",\"all_original_sector_mappings_preserved\":true,\"device_access\":false,\"before\":";
        PrintMetadata(*old);
        std::cout << ",\"after\":";
        PrintMetadata(*roundtrip);
        std::cout << "}\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Refused: " << e.what() << '\n';
        return 1;
    }
}
