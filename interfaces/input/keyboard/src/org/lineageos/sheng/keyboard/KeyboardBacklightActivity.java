// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.app.ActionBar;
import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.MenuItem;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

/** Device settings page for the keyboard light; uses the system wallpaper palette. */
public final class KeyboardBacklightActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable apply = this::applyPending;
    private int saved = -1;
    private int pending = -1;
    private SeekBar slider;
    private TextView value;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        ActionBar bar = getActionBar();
        if (bar != null) bar.setDisplayHomeAsUpEnabled(true);
        ScrollView scroll = new ScrollView(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPaddingRelative(dp(24), dp(24), dp(24), dp(24));
        scroll.addView(layout);
        value = new TextView(this);
        value.setTextAppearance(android.R.style.TextAppearance_Material_Title);
        layout.addView(value);
        slider = new SeekBar(this);
        slider.setContentDescription(getString(R.string.sheng_keyboard_backlight_title));
        slider.setMax(100);
        slider.setMinimumHeight(dp(56));
        saved = Settings.Secure.getInt(getContentResolver(), KeyboardBacklight.SETTING, -1);
        slider.setProgress(Math.max(0, Math.min(saved, 100)));
        showValue(saved);
        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar bar, int progress, boolean fromUser) {
                if (!fromUser) return;
                showValue(progress);
                pending = progress;
                handler.removeCallbacks(apply);
                handler.postDelayed(apply, 150);
            }
            @Override public void onStartTrackingTouch(SeekBar bar) {}
            @Override public void onStopTrackingTouch(SeekBar bar) { applyPending(); }
        });
        layout.addView(slider);
        TextView hint = new TextView(this);
        hint.setTextAppearance(android.R.style.TextAppearance_Material_Body1);
        hint.setText(R.string.sheng_keyboard_backlight_hint);
        layout.addView(hint);
        setContentView(scroll);
    }

    @Override public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override protected void onPause() {
        applyPending();
        super.onPause();
    }

    private void applyPending() {
        handler.removeCallbacks(apply);
        int percent = pending;
        pending = -1;
        if (percent < 0 || percent == saved) return;
        try {
            if (Settings.Secure.putInt(getContentResolver(), KeyboardBacklight.SETTING, percent)) {
                saved = percent;
                return;
            }
        } catch (SecurityException ignored) {
            // Restore the displayed value if the provider rejects the update.
        }
        slider.setProgress(Math.max(0, Math.min(saved, 100)));
        showValue(saved);
        Toast.makeText(this, R.string.sheng_keyboard_backlight_failed, Toast.LENGTH_LONG).show();
    }

    private void showValue(int percent) {
        if (percent < 0) value.setText(R.string.sheng_keyboard_backlight_unset);
        else if (percent == 0) value.setText(R.string.sheng_keyboard_backlight_off);
        else value.setText(getString(R.string.sheng_keyboard_backlight_value, percent));
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}

