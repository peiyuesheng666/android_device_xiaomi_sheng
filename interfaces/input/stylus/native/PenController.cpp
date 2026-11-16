// SPDX-License-Identifier: Apache-2.0
#include "PenController.h"

namespace sheng::stylus {
Result PenController::acquire(int type) {
    if (type != 3 && type != 8) return Result::Invalid;
    if (needsRelease()) return Result::Busy;
    if (!hardware_.stableOn()) return Result::Deferred;
    // THP must see the type before the original ioctl driver fallback.
    type_ = type;
    typeNotified_ = true;
    disconnectNotified_ = false;
    // A timed-out THP acknowledgement may follow a delivered notification.
    // Retain reset debt even then, but never invent a driver connection.
    if (!hardware_.notifyType(type | 16)) {
        releasing_ = true;
        return Result::Error;
    }
    if (!hardware_.setMode(20, type | 16)) {
        releasing_ = true;
        return Result::Error;
    }
    connected_ = true;
    releasing_ = false;
    return Result::Applied;
}

Result PenController::setMode(int mode, int value) {
    if (!connected_ || releasing_) return Result::Busy;
    const bool valid = (type_ == 8 && mode == 29 && (value == 0 || value == 1))
            || (mode == 37 && (value == 0 || value == 1))
            || (mode == 22 && (value == 49 || (value >= 0 && value <= 65535
                    && ((value & 255) == 1 || (value & 255) == 3))));
    if (!valid) return Result::Invalid;
    if (!hardware_.stableOn()) return Result::Deferred;
    if (mode == 37 && value == 1) ready_ = true;
    if (!hardware_.setMode(mode, value)) {
        // Keep attempted-ready/connection debt for release, but stop forwarding
        // immediately. The client has not yet received this failure and its
        // release transaction can arrive after the worker's next pressure read.
        releasing_ = true;
        return Result::Error;
    }
    if (mode == 37) {
        ready_ = value == 1;
        if (ready_) suspended_ = false;
    }
    return Result::Applied;
}

Result PenController::forwardProPressure(const uint8_t* report, size_t length) {
    if (!connected_ || !ready_ || releasing_ || suspended_) return Result::Busy;
    // Only the physically verified Pro layout is forwarded. Ordinary Focus
    // Pen uses type 3 and must acquire its own report-format evidence.
    if (type_ != 8 || !report || length != 15 || report[0] != 5) return Result::Invalid;
    const unsigned pressure = report[1] | (static_cast<unsigned>(report[2]) << 8);
    if (pressure > 0x4000) return Result::Invalid;
    if (!hardware_.stableOn()) return Result::Deferred;
    return hardware_.pressure(report, length) ? Result::Applied : Result::Error;
}

Result PenController::release() {
    if (!needsRelease()) {
        releasing_ = false;
        return Result::Applied;
    }
    releasing_ = true;
    if (!hardware_.stableOn()) return Result::Deferred;
    if (ready_) {
        if (!hardware_.setMode(37, 0)) return Result::Error;
        ready_ = false;
    }
    if (!disconnectNotified_) {
        if (!hardware_.notifyType(type_)) return Result::Error;
        disconnectNotified_ = true;
    }
    if (connected_) {
        if (!hardware_.setMode(20, type_)) return Result::Error;
        // Clear only after a successful ioctl. A later release must never
        // decrement the driver's connection count for this lease again.
        connected_ = false;
    }
    typeNotified_ = false;
    disconnectNotified_ = false;
    releasing_ = false;
    type_ = 0;
    suspended_ = true;
    return Result::Applied;
}
}  // namespace sheng::stylus
