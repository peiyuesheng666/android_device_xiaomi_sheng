// SPDX-License-Identifier: Apache-2.0
#include "ShengSensorFrame.h"
#include <json/json.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/xattr.h>
#include <unistd.h>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <memory>
#include <sstream>
#include <vector>

namespace sheng {
namespace {
constexpr int kSource[] = {1, 0, 2};
constexpr int kSign[] = {-1, 1, 1};
const char* const kAxes[] = {"x", "y", "z"};

bool Read(const std::string& path, std::string* value) {
    int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return false;
    value->clear();
    char buffer[4096];
    ssize_t size;
    while ((size = read(fd, buffer, sizeof(buffer))) > 0) value->append(buffer, size);
    close(fd);
    return size == 0 && value->size() <= 1024 * 1024;
}

bool Parse(const std::string& text, Json::Value* value) {
    Json::CharReaderBuilder builder;
    builder["rejectDupKeys"] = true;
    std::string error;
    std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    return reader->parse(text.data(), text.data() + text.size(), value, &error)
            && value->isObject();
}

std::string Encode(const Json::Value& value) {
    Json::StreamWriterBuilder builder;
    builder["indentation"] = "";
    if (!value.isObject()) return Json::writeString(builder, value);
    // SSC's registry parser explicitly requires type before data. JsonCpp's
    // alphabetical object output puts data first and is incompatible with it.
    std::string output = "{";
    bool first = true;
    auto append = [&](const std::string& key) {
        if (!first) output += ',';
        first = false;
        output += Json::writeString(builder, Json::Value(key)) + ':' + Encode(value[key]);
    };
    for (const char* key : {"owner", "type", "ver", "data"}) {
        if (value.isMember(key)) append(key);
    }
    for (const std::string& key : value.getMemberNames()) {
        if (key != "owner" && key != "type" && key != "ver" && key != "data") append(key);
    }
    return output + '}';
}

bool AtomicWrite(const std::string& path, const std::string& value) {
    struct stat metadata{};
    bool existing = lstat(path.c_str(), &metadata) == 0;
    if (existing && !S_ISREG(metadata.st_mode)) return false;
    std::string temporary = path + ".sheng-tmp";
    int fd = open(temporary.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return false;
    bool ok = true;
    size_t offset = 0;
    while (offset < value.size()) {
        ssize_t size = write(fd, value.data() + offset, value.size() - offset);
        if (size < 0 && errno == EINTR) continue;
        if (size <= 0) { ok = false; break; }
        offset += size;
    }
    if (existing) {
        ok &= fchmod(fd, metadata.st_mode & 07777) == 0;
        ok &= fchown(fd, metadata.st_uid, metadata.st_gid) == 0;
        ssize_t count = listxattr(path.c_str(), nullptr, 0);
        if (count > 0) {
            std::vector<char> names(count);
            ok &= listxattr(path.c_str(), names.data(), count) == count;
            for (size_t index = 0; index < names.size() && ok;) {
                const char* name = names.data() + index;
                ssize_t bytes = getxattr(path.c_str(), name, nullptr, 0);
                if (bytes < 0) { ok = false; break; }
                std::vector<char> data(bytes);
                ok &= getxattr(path.c_str(), name, data.data(), bytes) == bytes;
                std::vector<char> current(bytes);
                ssize_t present = fgetxattr(fd, name, current.data(), bytes);
                if (present != bytes || current != data) {
                    ok &= fsetxattr(fd, name, data.data(), bytes, 0) == 0;
                }
                index += strlen(name) + 1;
            }
        } else if (count < 0) ok = false;
    }
    ok &= fsync(fd) == 0;
    close(fd);
    if (!ok || rename(temporary.c_str(), path.c_str()) != 0) {
        unlink(temporary.c_str());
        return false;
    }
    auto slash = path.find_last_of('/');
    int directory = open(path.substr(0, slash).c_str(), O_DIRECTORY | O_RDONLY | O_CLOEXEC);
    if (directory < 0) return false;
    ok = fsync(directory) == 0;
    close(directory);
    return ok;
}

bool Number(const Json::Value& leaf, double* output) {
    if (!leaf.isObject() || leaf["type"] != "flt" || !leaf["data"].isString()) return false;
    std::string text = leaf["data"].asString();
    char* end;
    *output = strtod(text.c_str(), &end);
    return end != text.c_str() && *end == '\0' && std::isfinite(*output);
}

Json::Value Leaf(const Json::Value& old, double value) {
    Json::Value result = old;
    std::ostringstream text;
    text << std::setprecision(17) << (value == 0 ? 0 : value);
    result["data"] = text.str();
    return result;
}

bool Convert(Json::Value* group, bool matrix, bool unsignedAxes) {
    const Json::Value before = *group;
    int size = matrix ? 9 : 3;
    for (int index = 0; index < size; index++) {
        int row = matrix ? index / 3 : index;
        int column = matrix ? index % 3 : 0;
        std::string target = matrix ? std::to_string(row) + "_" + std::to_string(column) : kAxes[row];
        std::string source = matrix ? std::to_string(kSource[row]) + "_" + std::to_string(kSource[column])
                                    : kAxes[kSource[row]];
        double value;
        if (!Number(before[source], &value)) return false;
        int sign = unsignedAxes ? 1 : kSign[row] * (matrix ? kSign[column] : 1);
        (*group)[target] = Leaf(before[target], sign * value);
    }
    return true;
}

bool AxesEqual(const Json::Value& group, const char* x, const char* y) {
    return group["x"]["data"] == x && group["y"]["data"] == y && group["z"]["data"] == "+z";
}
}

bool MigrateSensorFrame(const std::string& root, std::string* error) {
    // Journal lives outside SSC's group directory. It contains exact before/
    // after bytes so an interrupted boot resumes without rotating twice.
    const std::string journalPath = root + "/../.sheng-landscape-frame-v1.json";
    std::string text;
    Json::Value journal;
    if (Read(journalPath, &text)) {
        if (!Parse(text, &journal) || journal["schema"] != 1 || !journal["files"].isObject()) {
            *error = "Invalid sensor frame migration journal"; return false;
        }
        if (journal["complete"].asBool()) {
            // Repair serialization from the initial diagnostic, retaining all
            // current values (including any later runtime calibration).
            for (const std::string& name : journal["files"].getMemberNames()) {
                Json::Value current;
                if (name.find('/') != std::string::npos || name.find("..") != std::string::npos ||
                        !Read(root + "/" + name, &text) || !Parse(text, &current)) {
                    *error = "Cannot validate completed sensor frame group: " + name; return false;
                }
                std::string ordered = Encode(current);
                if (text != ordered && !AtomicWrite(root + "/" + name, ordered)) {
                    *error = "Cannot repair sensor registry serialization: " + name; return false;
                }
            }
            return true;
        }
    } else {
        if (errno != ENOENT) { *error = "Cannot read sensor frame journal"; return false; }
        journal["schema"] = 1;
        journal["complete"] = false;
        journal["files"] = Json::Value(Json::objectValue);
        for (const char* sensor : {"icm4x6xx_0_platform", "qmc630x_0_platform"}) {
            std::string name = std::string(sensor) + ".orient";
            if (!Read(root + "/" + name, &text)) {
                if (errno == ENOENT) continue;  // Fresh registry imports adapted ODM defaults.
                *error = "Cannot read " + name; return false;
            }
            Json::Value orientation;
            if (!Parse(text, &orientation) || !orientation[name].isObject()) {
                *error = "Invalid " + name; return false;
            }
            bool imu = std::string(sensor) == "icm4x6xx_0_platform";
            Json::Value& axes = orientation[name];
            if (AxesEqual(axes, imu ? "-y" : "+y", imu ? "+x" : "-x")) continue;
            if (!AxesEqual(axes, imu ? "-x" : "+x", imu ? "-y" : "+y")) {
                *error = "Unknown sensor axis frame: " + name; return false;
            }
            journal["files"][name]["before"] = text;
            axes["x"]["data"] = imu ? "-y" : "+y";
            axes["y"]["data"] = imu ? "+x" : "-x";
            axes["x"]["ver"] = "2";
            axes["y"]["ver"] = imu ? "1" : "2";
            journal["files"][name]["after"] = Encode(orientation);
            for (const char* calibration : imu ? std::vector<const char*>{"accel.fac_cal", "gyro.fac_cal"}
                                               : std::vector<const char*>{"mag.fac_cal", "mag.fac_cal_2"}) {
                for (const char* suffix : {"bias", "bias_original", "gain", "corr_mat"}) {
                    std::string file = std::string(sensor) + "." + calibration + "." + suffix;
                    if (!Read(root + "/" + file, &text)) {
                        if (errno == ENOENT) continue;
                        *error = "Cannot read " + file; return false;
                    }
                    Json::Value value;
                    if (!Parse(text, &value) || !value[file].isObject() ||
                            !Convert(&value[file], std::string(suffix) == "corr_mat",
                                     std::string(suffix) == "gain")) {
                        *error = "Invalid calibration group: " + file; return false;
                    }
                    journal["files"][file]["before"] = text;
                    journal["files"][file]["after"] = Encode(value);
                }
            }
        }
        if (journal["files"].empty()) return true;
        if (!AtomicWrite(journalPath, Encode(journal))) {
            *error = "Cannot save sensor frame migration journal"; return false;
        }
    }
    // Preflight all groups before writing any; never overwrite calibration
    // changed independently since an incomplete transaction.
    for (const std::string& name : journal["files"].getMemberNames()) {
        if (name.find('/') != std::string::npos || name.find("..") != std::string::npos ||
                !Read(root + "/" + name, &text) ||
                (text != journal["files"][name]["before"].asString() &&
                 text != journal["files"][name]["after"].asString())) {
            *error = "Sensor registry changed during migration: " + name; return false;
        }
    }
    for (const std::string& name : journal["files"].getMemberNames()) {
        const std::string after = journal["files"][name]["after"].asString();
        if (!Read(root + "/" + name, &text) || (text != after && !AtomicWrite(root + "/" + name, after))) {
            *error = "Cannot migrate " + name; return false;
        }
    }
    journal["complete"] = true;
    if (!AtomicWrite(journalPath, Encode(journal))) {
        *error = "Cannot finalize sensor frame migration journal"; return false;
    }
    return true;
}
}
