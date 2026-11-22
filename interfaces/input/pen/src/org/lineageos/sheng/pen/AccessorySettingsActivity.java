// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** Stable Settings tile; both accessory pages live in the pen application. */
public final class AccessorySettingsActivity extends Activity {
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        startActivity(new Intent(this, CompatibilityActivity.class));
        finish();
    }
}
