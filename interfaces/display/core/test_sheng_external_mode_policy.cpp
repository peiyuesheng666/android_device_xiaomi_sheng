#include "sheng_external_mode_policy.h"
#include <cassert>
#include <cstdint>

struct Mode { uint32_t x_pixels, y_pixels, fps; };

int main() {
  using sdm::ShengPreferExternalMode;
  assert(ShengPreferExternalMode(Mode{1920,1080,60}, Mode{3840,2160,30}));
  assert(!ShengPreferExternalMode(Mode{4096,2160,30}, Mode{1920,1080,60}));
  assert(ShengPreferExternalMode(Mode{3840,2160,60}, Mode{1920,1080,60}));
  assert(ShengPreferExternalMode(Mode{2560,1440,144}, Mode{3840,2160,120}));
  assert(!ShengPreferExternalMode(Mode{0,1080,240}, Mode{1920,1080,60}));
  assert(!ShengPreferExternalMode(Mode{1920,1080,0}, Mode{1920,1080,60}));
  assert(ShengPreferExternalMode(Mode{1920,1080,60}, Mode{}));
  assert(!ShengPreferExternalMode(Mode{1920,1080,60}, Mode{1920,1080,60}));
  assert(ShengPreferExternalMode(Mode{100000,100000,60}, Mode{65536,65536,60}));
}
