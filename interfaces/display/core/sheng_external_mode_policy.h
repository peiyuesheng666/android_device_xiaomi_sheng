#pragma once

#include <cstdint>

namespace sdm {

// Only compare valid sink-advertised modes. Preserve enumeration order for ties.
template <typename Mode>
bool ShengPreferExternalMode(const Mode &candidate, const Mode &selected) {
  if (!candidate.x_pixels || !candidate.y_pixels || !candidate.fps) return false;
  if (!selected.x_pixels || !selected.y_pixels || !selected.fps) return true;
  if (candidate.fps != selected.fps) return candidate.fps > selected.fps;
  return uint64_t(candidate.x_pixels) * candidate.y_pixels >
         uint64_t(selected.x_pixels) * selected.y_pixels;
}

}  // namespace sdm
