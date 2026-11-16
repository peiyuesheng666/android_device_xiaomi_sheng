// SPDX-License-Identifier: Apache-2.0
// A link-only ELF SONAME declaration, with no ART or signal implementation.
// It must never be installed; sheng-face loads the real platform libsigchain.so.
extern "C" __attribute__((visibility("hidden"))) void sheng_signal_link_only() {
    __builtin_trap();
}
