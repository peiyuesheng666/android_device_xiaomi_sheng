// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.indicator;

import android.app.Activity;
import android.content.res.Configuration;
import android.os.Bundle;
import android.os.SystemProperties;
import android.preference.PreferenceFragment;
import android.preference.SwitchPreference;
import android.view.MenuItem;
import android.widget.Toast;

/** Device-wide control for the physical top RGB indicator. */
public final class IndicatorSettingsActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        if ((getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES) setTheme(android.R.style.Theme_DeviceDefault);
        super.onCreate(state);
        setTitle(R.string.app_name);
        if (getActionBar() != null) getActionBar().setDisplayHomeAsUpEnabled(true);
        if (state == null) getFragmentManager().beginTransaction()
                .replace(android.R.id.content, new IndicatorPreferences()).commit();
    }

    @Override public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) { finish(); return true; }
        return super.onOptionsItemSelected(item);
    }

    public static final class IndicatorPreferences extends PreferenceFragment {
        private static final String PROPERTY = "persist.sys.sheng.indicator";
        private SwitchPreference toggle;

        @Override public void onCreate(Bundle state) {
            super.onCreate(state);
            addPreferencesFromResource(R.xml.preferences);
            toggle = (SwitchPreference) findPreference("indicator_enabled");
            toggle.setOnPreferenceChangeListener((preference, value) -> {
                boolean enabled = Boolean.TRUE.equals(value);
                try {
                    SystemProperties.set(PROPERTY, enabled ? "1" : "0");
                    if (SystemProperties.getBoolean(PROPERTY, false) == enabled) return true;
                } catch (RuntimeException unavailable) { /* Preserve the displayed actual setting. */ }
                Toast.makeText(getActivity(), R.string.setting_failed, Toast.LENGTH_SHORT).show();
                return false;
            });
        }

        @Override public void onResume() {
            super.onResume();
            toggle.setChecked(SystemProperties.getBoolean(PROPERTY, false));
        }
    }
}
