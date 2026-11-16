// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "TouchControl.h"

namespace sheng::touch {
constexpr uint16_t kSuperReportMode = 202;
constexpr char kHighReportProperty[] = "persist.vendor.sheng.touch.report_high";
class RateTransport {
  public:
    virtual ~RateTransport() = default;
    virtual bool setReport(Io& io, bool enabled, Cancelled cancelled, void* context) = 0;
};
bool isReportAcknowledgement(const TouchCommand& command);
std::unique_ptr<RateTransport> makeRateTransport();
Result applyReportRate(Io& io, RateTransport& transport, int desired,
                       Cancelled cancelled = nullptr, void* context = nullptr);
}  // namespace sheng::touch
