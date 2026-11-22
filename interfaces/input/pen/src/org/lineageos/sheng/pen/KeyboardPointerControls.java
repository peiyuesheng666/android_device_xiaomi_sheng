// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.content.Context;
import android.content.Intent;
import android.database.ContentObserver;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

/** Native touchpad controls, sharing the platform's authoritative settings. */
final class KeyboardPointerControls extends LinearLayout {
    private final TextView speedLabel;
    private final SeekBar speed;
    private final Switch natural;
    private boolean refreshing;
    private boolean tracking;
    private final ContentObserver observer = new ContentObserver(new Handler(Looper.getMainLooper())) {
        @Override public void onChange(boolean self) { refresh(); }
    };

    KeyboardPointerControls(Context context, int surface, int ink, int tint, int accent) {
        super(context);
        setOrientation(VERTICAL);
        setPadding(0, dp(20), 0, 0);
        speedLabel = new TextView(context);
        speedLabel.setTextColor(ink); speedLabel.setTextSize(20);
        addView(speedLabel);
        speed = new SeekBar(context);
        speed.setMax(14); // Platform range -7..7, zero is the platform default.
        speed.setContentDescription(context.getString(R.string.keyboard_pointer_speed));
        KeyboardPageView.styleSlider(speed, tint, accent);
        addView(speed, new LayoutParams(-1, dp(64)));
        natural = new KeyboardMaterialSwitch(context);
        KeyboardPageView.styleSwitch(natural, surface, ink, tint, accent);
        natural.setText(R.string.keyboard_natural_scroll);
        natural.setTextSize(17); natural.setTextColor(ink);
        natural.setMinimumHeight(dp(64));
        addView(natural);
        speed.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar bar, int value, boolean user) {
                if (user) showSpeed(value - 7);
            }
            @Override public void onStartTrackingTouch(SeekBar bar) { tracking = true; }
            @Override public void onStopTrackingTouch(SeekBar bar) {
                tracking = false;
                try {
                    request("speed", bar.getProgress() - 7);
                }
                catch (SecurityException | IllegalArgumentException error) { failed(); }
                refresh();
            }
        });
        natural.setOnCheckedChangeListener((button, enabled) -> {
            if (refreshing) return;
            try {
                request("natural", enabled ? 1 : 0);
            }
            catch (SecurityException | IllegalArgumentException error) { failed(); }
            refresh();
        });
        refresh();
    }

    private void failed() {
        Toast.makeText(getContext(), R.string.keyboard_write_failed, Toast.LENGTH_LONG).show();
    }

    private void request(String control, int value) {
        getContext().sendBroadcast(new Intent("org.lineageos.sheng.keyboard.SET_POINTER")
                .setPackage("org.lineageos.sheng.keyboard")
                .putExtra("control", control).putExtra("value", value),
                android.Manifest.permission.WRITE_SECURE_SETTINGS);
        // Displayed values come from the native System observer, never a presumed ACK.
    }

    private void showSpeed(int value) {
        speedLabel.setText(getContext().getString(R.string.keyboard_pointer_speed_value, value));
    }

    private void refresh() {
        if (tracking) return;
        refreshing = true;
        try {
            // InputSettings uses USER_CURRENT (-2), which requires cross-user
            // permission even for user 0. These controls belong to this user;
            // use its resolver instead of granting INTERACT_ACROSS_USERS_FULL.
            int value = Settings.System.getInt(getContext().getContentResolver(),
                    Settings.System.TOUCHPAD_POINTER_SPEED, 0);
            speed.setProgress(Math.max(0, Math.min(14, value + 7)));
            showSpeed(value);
            natural.setChecked(Settings.System.getInt(getContext().getContentResolver(),
                    Settings.System.TOUCHPAD_NATURAL_SCROLLING, 1) == 1);
        } finally { refreshing = false; }
    }

    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        getContext().getContentResolver().registerContentObserver(
                Settings.System.getUriFor(Settings.System.TOUCHPAD_POINTER_SPEED), false, observer);
        getContext().getContentResolver().registerContentObserver(
                Settings.System.getUriFor(Settings.System.TOUCHPAD_NATURAL_SCROLLING), false, observer);
        refresh();
    }

    @Override protected void onDetachedFromWindow() {
        getContext().getContentResolver().unregisterContentObserver(observer);
        super.onDetachedFromWindow();
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
