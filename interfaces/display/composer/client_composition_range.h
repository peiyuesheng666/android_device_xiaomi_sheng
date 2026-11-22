// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sdm {
struct DisplayCompositionInput {
  int32_t dataspace;
  bool blends;
  bool protected_content;
};

// The condition is derived only from this frame's input, so accepting the
// previous GPU result cannot turn the fallback off on alternating frames.
inline bool NeedsMixedDataspaceClientComposition(
    const std::vector<DisplayCompositionInput> &layers) {
  int32_t first_dataspace = 0;
  bool mixed = false, blends = false;
  for (const auto &layer : layers) {
    if (layer.protected_content) return false;
    if (layer.dataspace != 0) {
      if (first_dataspace == 0) first_dataspace = layer.dataspace;
      mixed |= layer.dataspace != first_dataspace;
    }
    blends |= layer.blends;
  }
  return mixed && blends;
}

struct ClientCompositionLayer {
  bool client;
  bool blends;
  bool protected_content;
};

inline bool IsToastCompositionLayer(const std::string &name) {
  return name.compare(0, 10, "VRI[Toast]") == 0 ||
         name.compare(0, 9, "VRI-Toast") == 0;
}

// A toast can be hardware eligible even when its backdrop needs the legacy
// compositor workaround. Keep the backdrop and toast in one blend operation.
// Layers above the toast are unaffected; protected content stays on hardware.
inline std::vector<size_t> ToastClientCompositionPromotions(
    const std::vector<ClientCompositionLayer> &layers, size_t toast) {
  if (toast >= layers.size()) return {};
  for (size_t i = 0; i <= toast; ++i)
    if (layers[i].protected_content) return {};
  std::vector<size_t> result;
  for (size_t i = 0; i <= toast; ++i)
    if (!layers[i].client) result.push_back(i);
  return result;
}

// Use original client requirements, not the composition accepted from the last
// validate. Desktop shadows require a client target even in a single dataspace.
// Keep translucent overlays above that target in the same blend operation on
// legacy SDM; adding/removing a toast must not switch its backdrop's blend path.
inline std::vector<size_t> TranslucentClientCompositionPromotions(
    const std::vector<ClientCompositionLayer> &layers) {
  size_t first = layers.size(), last = 0;
  for (size_t i = 0; i < layers.size(); ++i) {
    if (layers[i].client && first == layers.size()) first = i;
    if (layers[i].blends || layers[i].client) last = i;
  }
  if (first >= last) return {};
  for (size_t i = first; i <= last; ++i)
    if (layers[i].protected_content) return {};
  std::vector<size_t> result;
  for (size_t i = first; i <= last; ++i)
    if (!layers[i].client) result.push_back(i);
  return result;
}

// A single client target cannot interleave its lower and upper contents with
// a translucent hardware layer. SurfaceFlinger intentionally does not punch a
// clear-client-target hole for such a layer: it has to blend with what is below.
// Keep the affected client interval contiguous, leaving outside overlays alone.
inline std::vector<size_t> ClientCompositionPromotions(
    const std::vector<ClientCompositionLayer> &layers) {
  size_t first = layers.size(), last = 0;
  for (size_t i = 0; i < layers.size(); ++i) {
    if (layers[i].client) {
      if (first == layers.size()) first = i;
      last = i;
    }
  }
  if (first >= last) return {};
  bool unsafe = false;
  for (size_t i = first + 1; i < last; ++i) {
    // Never move a protected hardware layer into an unprotected client target.
    if (!layers[i].client && layers[i].protected_content) return {};
    unsafe |= !layers[i].client && layers[i].blends;
  }
  if (!unsafe) return {};
  std::vector<size_t> result;
  for (size_t i = first + 1; i < last; ++i)
    if (!layers[i].client) result.push_back(i);
  return result;
}
}  // namespace sdm
