// SPDX-License-Identifier: Apache-2.0
package vendor.lineage.sheng.stylus;

/** One client token owns the original driver connection. The server reads real HID. */
@VintfStability
interface IPenController {
    const int APPLIED = 0;
    const int DEFERRED = 1;
    const int BUSY = 2;
    const int INVALID = 3;
    const int ERROR = 4;
    int acquire(in IBinder owner, int product, String address);
    int setMode(in IBinder owner, int mode, int value);
    int release(in IBinder owner);
    long getForwardedCount(in IBinder owner);
}
