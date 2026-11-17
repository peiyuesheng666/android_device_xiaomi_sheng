// SPDX-License-Identifier: Apache-2.0
#include "../interfaces/display/composer/client_composition_range.h"
#include <cassert>
#include <vector>

int main() {
  assert(!sdm::NeedsMixedDataspaceClientComposition({}));
  assert(!sdm::NeedsMixedDataspaceClientComposition({{1, true, false}, {1, true, false}}));
  assert(!sdm::NeedsMixedDataspaceClientComposition({{1, false, false}, {2, false, false}}));
  assert(sdm::NeedsMixedDataspaceClientComposition({{1, false, false}, {2, true, false}}));
  assert(!sdm::NeedsMixedDataspaceClientComposition({{1, false, true}, {2, true, false}}));
  assert(!sdm::NeedsMixedDataspaceClientComposition({{0, true, false}, {2, true, false}}));

  using sdm::ClientCompositionLayer;
  using sdm::ClientCompositionPromotions;
  const ClientCompositionLayer hw{false, false, false};
  const ClientCompositionLayer alpha{false, true, false};
  const ClientCompositionLayer gpu{true, true, false};
  const ClientCompositionLayer secure{false, true, true};
  assert(ClientCompositionPromotions({}).empty());
  assert(ClientCompositionPromotions({alpha, hw, alpha}).empty());
  assert(ClientCompositionPromotions({alpha, gpu, alpha}).empty());
  assert(ClientCompositionPromotions({gpu, hw, gpu}).empty());
  assert(ClientCompositionPromotions({gpu, secure, gpu}).empty());
  assert((ClientCompositionPromotions({gpu, gpu, alpha, hw, gpu, alpha}) ==
          std::vector<size_t>{2, 3}));
  // The observed media-viewer stack: the affected middle interval is promoted,
  // while the screen decorations outside it remain hardware overlays.
  assert((ClientCompositionPromotions({gpu, gpu, alpha, alpha, gpu, alpha, alpha}) ==
          std::vector<size_t>{2, 3}));
  assert(ClientCompositionPromotions({gpu, gpu, gpu, gpu, gpu, alpha, alpha}).empty());
  // Exhaustively check that a repaired unprotected stack is a fixed point and
  // never changes layers outside the original first/last client interval.
  for (unsigned bits = 0; bits < 6561; ++bits) {
    unsigned code = bits;
    std::vector<ClientCompositionLayer> stack;
    size_t first = 8, last = 0;
    for (size_t i = 0; i < 8; ++i) {
      const unsigned state = code % 3; code /= 3;
      stack.push_back(state == 0 ? hw : state == 1 ? alpha : gpu);
      if (state == 2) { if (first == 8) first = i; last = i; }
    }
    const auto changes = ClientCompositionPromotions(stack);
    for (size_t index : changes) {
      assert(first < index && index < last && !stack[index].client);
      stack[index].client = true;
    }
    assert(ClientCompositionPromotions(stack).empty());
  }
}
