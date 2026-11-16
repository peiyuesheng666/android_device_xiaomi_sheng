// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <string>

namespace sheng::stylus {
// Boot-local intent marker. An interrupted driver ioctl has no atomic readback
// of its connection-count effect. A replacement process must fail closed,
// rather than guess a decrement or silently acquire an additional connection.
class PenLeaseJournal {
  public:
    explicit PenLeaseJournal(const std::string& directory);
    ~PenLeaseJournal();
    bool blocked() const { return blocked_; }
    bool begin();
    bool finish();
  private:
    int directory_ = -1;
    bool blocked_ = true, owned_ = false;
};
}  // namespace sheng::stylus
