#ifndef FOCUSPEN_IDENTITY_H
#define FOCUSPEN_IDENTITY_H
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

static inline bool focuspen_known_id(unsigned bus, unsigned vendor, unsigned product) {
    return bus == 0x0005 && vendor == 0x0022 &&
           (product == 0x4d80 || product == 0x5081);
}

/* Pro report 5 can be exposed as a keyboard (+) by the generic HID descriptor.
 * Suppress every input child of this precise BT product; hidraw remains usable.
 * Preserve the legacy pen's existing policy for its separate button devices. */
static inline bool focuspen_suppress_input(unsigned bus, unsigned vendor,
                                           unsigned product, const char *name) {
    if (!focuspen_known_id(bus, vendor, product)) return false;
    return product == 0x5081 || (name && !strcmp(name, "Xiaomi Focus Pen"));
}

static inline bool focuspen_match_hid(const char *uevent, const char *want_id,
                                      const char *want_name) {
    unsigned bus = 0, vendor = 0, product = 0;
    const char *id = strstr(uevent, "HID_ID=");
    bool known = id && sscanf(id, "HID_ID=%x:%x:%x", &bus, &vendor, &product) == 3
                 && focuspen_known_id(bus, vendor, product);
    bool id_ok = want_id == NULL ? known : (!*want_id || strstr(uevent, want_id));
    bool name_ok = !want_name || !*want_name || strstr(uevent, want_name);
    /* The built-in selector is a label, not an additional hardware identity.
     * Explicit custom names and explicit ID selectors retain their old meaning. */
    if (!want_id && known && want_name && !strcmp(want_name, "HID_NAME=Xiaomi Focus Pen"))
        name_ok = true;
    return id_ok && name_ok;
}
#endif
