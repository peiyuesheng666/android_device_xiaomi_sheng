// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.content.Context;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.database.ContentObserver;
import android.graphics.drawable.ClipDrawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.graphics.drawable.RippleDrawable;
import android.hardware.Sensor;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.Button;
import android.widget.SeekBar;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

/** In-process keyboard page. Only settings are written; the keyboard service owns I/O. */
final class KeyboardPageView extends LinearLayout {
    private static final String LEVEL = "sheng_keyboard_backlight_percent";
    private static final String AUTO = "sheng_keyboard_backlight_auto";
    private static final String EFFECTIVE = "sheng_keyboard_backlight_effective_percent";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable commit = this::commitLevel;
    private final ContentObserver observer = new ContentObserver(handler) {
        @Override public void onChange(boolean self) { refresh(); }
    };
    private final SeekBar slider;
    private final Switch automatic;
    private final TextView value;
    private int pending = -1;
    private boolean refreshing;

    KeyboardPageView(Context context, int surface, int ink, int muted, int tint, int accent) {
        super(context);
        setOrientation(VERTICAL);
        setPadding(dp(22), dp(24), dp(22), dp(24));
        setBackground(shape(surface, 24));
        value = label(context.getString(R.string.keyboard_brightness), 20, ink);
        addView(value);
        slider = new SeekBar(context);
        slider.setMax(100);
        slider.setContentDescription(context.getString(R.string.keyboard_brightness));
        styleSlider(slider, tint, accent);
        addView(slider, new LayoutParams(-1, dp(64)));
        automatic = new KeyboardMaterialSwitch(context);
        styleSwitch(automatic, surface, ink, tint, accent);
        automatic.setText(R.string.keyboard_auto);
        automatic.setTextColor(ink); automatic.setTextSize(17);
        automatic.setMinimumHeight(dp(64)); addView(automatic);
        SensorManager sensors = context.getSystemService(SensorManager.class);
        boolean hasLight = sensors != null && sensors.getDefaultSensor(Sensor.TYPE_LIGHT) != null;
        automatic.setEnabled(hasLight);
        // Keep the page focused on controls, not explanatory paragraphs.
        if (!hasLight) {
            automatic.setContentDescription(context.getString(R.string.keyboard_auto_unavailable));
        }
        addView(new KeyboardPointerControls(context, surface, ink, tint, accent), new LayoutParams(-1, -2));
        Button keyboardSettings = new Button(context);
        keyboardSettings.setText(R.string.keyboard_system_settings);
        keyboardSettings.setTextColor(ink);
        keyboardSettings.setAllCaps(false);
        keyboardSettings.setMinHeight(dp(48));
        keyboardSettings.setMinimumHeight(dp(48));
        keyboardSettings.setPadding(dp(20), dp(12), dp(20), dp(12));
        keyboardSettings.setBackground(new RippleDrawable(
                ColorStateList.valueOf((ink & 0x00ffffff) | 0x24000000),
                shape(tint, 20), shape(0xffffffff, 20)));
        keyboardSettings.setOnClickListener(view -> {
            // Keep layouts/accessibility in the system's authoritative page.
            Intent intent = new Intent(Settings.ACTION_HARD_KEYBOARD_SETTINGS);
            intent.setPackage("com.android.settings");
            try {
                context.startActivity(intent);
            } catch (ActivityNotFoundException | SecurityException error) {
                Toast.makeText(context, R.string.accessories_keyboard_unavailable,
                        Toast.LENGTH_SHORT).show();
            }
        });
        LayoutParams keyboardSettingsParams = new LayoutParams(-1, -2);
        keyboardSettingsParams.topMargin = dp(16);
        addView(keyboardSettings, keyboardSettingsParams);
        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar bar, int level, boolean user) {
                if (!user) return;
                value.setText(context.getString(R.string.keyboard_level, level));
                pending = level; handler.removeCallbacks(commit); handler.postDelayed(commit, 150);
            }
            @Override public void onStartTrackingTouch(SeekBar bar) {}
            @Override public void onStopTrackingTouch(SeekBar bar) { commitLevel(); }
        });
        automatic.setOnCheckedChangeListener((button, enabled) -> {
            if (refreshing) return;
            commitLevel();
            write(AUTO, enabled ? 1 : 0); refresh();
        });
        refresh();
    }

    void refresh() {
        if (pending >= 0 || slider.isPressed()) return;
        refreshing = true;
        try {
            boolean auto = Settings.Secure.getInt(getContext().getContentResolver(), AUTO, 0) != 0;
            int level = Settings.Secure.getInt(getContext().getContentResolver(), LEVEL, -1);
            int displayed = auto ? Settings.Secure.getInt(getContext().getContentResolver(), EFFECTIVE, -1) : level;
            automatic.setChecked(auto);
            slider.setEnabled(!auto);
            slider.setAlpha(auto ? .38f : 1f);
            slider.setProgress(Math.max(0, Math.min(100, displayed)));
            value.setText(displayed >= 0 ? getContext().getString(R.string.keyboard_level, displayed)
                    : auto ? getContext().getString(R.string.keyboard_auto)
                    : getContext().getString(R.string.keyboard_level_unset));
        } finally { refreshing = false; }
    }

    private void commitLevel() {
        handler.removeCallbacks(commit);
        int level = pending; pending = -1;
        if (level >= 0) { write(LEVEL, level); refresh(); }
    }

    private void write(String key, int value) {
        try {
            if (Settings.Secure.putInt(getContext().getContentResolver(), key, value)) return;
        } catch (SecurityException unavailable) { /* Report failure, never pretend hardware applied it. */ }
        Toast.makeText(getContext(), R.string.keyboard_write_failed, Toast.LENGTH_LONG).show();
    }

    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        getContext().getContentResolver().registerContentObserver(Settings.Secure.getUriFor(LEVEL), false, observer);
        getContext().getContentResolver().registerContentObserver(Settings.Secure.getUriFor(AUTO), false, observer);
        getContext().getContentResolver().registerContentObserver(Settings.Secure.getUriFor(EFFECTIVE), false, observer);
        refresh();
    }
    @Override protected void onDetachedFromWindow() {
        commitLevel();
        getContext().getContentResolver().unregisterContentObserver(observer);
        super.onDetachedFromWindow();
    }
    static void styleSlider(SeekBar slider, int tint, int accent) {
        // Same geometry as the Dolby gain slider: 10dp rounded track, 4x36dp handle.
        LayerDrawable track = new LayerDrawable(new android.graphics.drawable.Drawable[]{
                sliderShape(slider, tint, 20), new ClipDrawable(sliderShape(slider, accent, 20), Gravity.START, ClipDrawable.HORIZONTAL)});
        track.setId(0, android.R.id.background); track.setId(1, android.R.id.progress);
        for (int i = 0; i < 2; i++) {
            track.setLayerHeight(i, sliderDp(slider, 10)); track.setLayerGravity(i, Gravity.CENTER_VERTICAL);
        }
        slider.setProgressDrawable(track);
        GradientDrawable handle = sliderShape(slider, accent, 2); handle.setSize(sliderDp(slider, 4), sliderDp(slider, 36));
        slider.setThumb(handle); slider.setThumbOffset(sliderDp(slider, 2));
        slider.setThumbTintList(ColorStateList.valueOf(accent));
        slider.setProgressTintList(ColorStateList.valueOf(accent));
        slider.setProgressBackgroundTintList(ColorStateList.valueOf(tint));
        slider.setMinHeight(sliderDp(slider, 56)); slider.setSplitTrack(false);
    }

    /** Material-sized pill/inner thumb, keeping native Switch input/accessibility. */
    static void styleSwitch(Switch control, int surface, int ink, int tint, int accent) {
        ((KeyboardMaterialSwitch) control).setColors(surface, ink, tint, accent);
    }

    private static int sliderDp(SeekBar slider, int value) {
        return Math.round(value * slider.getResources().getDisplayMetrics().density);
    }

    private static GradientDrawable sliderShape(SeekBar slider, int color, int radius) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color);
        shape.setCornerRadius(sliderDp(slider, radius)); return shape;
    }

    private TextView label(String text, int size, int color) {
        TextView view = new TextView(getContext()); view.setText(text);
        view.setTextSize(size); view.setTextColor(color); return view;
    }
    private GradientDrawable shape(int color, int radius) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color);
        shape.setCornerRadius(dp(radius)); return shape;
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
