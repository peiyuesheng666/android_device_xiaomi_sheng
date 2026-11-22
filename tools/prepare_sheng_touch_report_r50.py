#!/usr/bin/env python3
"""Mirror only touch-report build inputs and isolate the already deferred face policy."""
import prepare_sheng_bt_touch_batch as batch

batch.SCOPES = ['device.mk', 'interfaces/input/touch',
                'sepolicy/vendor/file_contexts', 'sepolicy/vendor/property_contexts',
                'overlay/SettingsResOverlaySheng']
if __name__ == '__main__':
    batch.main()
