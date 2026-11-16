// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

import android.app.KeyguardManager;
import android.content.Intent;
import android.os.Bundle;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.Button;
import android.widget.TextView;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.util.TypedValue;

/** Settings entry. Every enrollment, enabling operation and deletion requires credentials. */
public final class FaceUnlockActivity extends FaceLabActivity {
    public static boolean supported() { return FaceUnlockSettings.supported(); }
    private static final int ENABLE = 110, DELETE = 111;
    private Switch toggle;
    private int pending;
    private boolean refreshing;

    @Override protected boolean isSystemFace() { return true; }
    @Override protected TemplateStore createTemplateStore() { return new TemplateStore(this, true); }
    @Override protected void addSystemControls(LinearLayout root) {
        toggle = new Switch(this); toggle.setText("使用人脸解锁"); toggle.setMinHeight(
                Math.round(56 * getResources().getDisplayMetrics().density));
        toggle.setChecked(FaceUnlockSettings.enabled(this)); root.addView(toggle);
        toggle.setOnCheckedChangeListener((button, checked) -> {
            if (refreshing) return;
            if (!checked) { FaceUnlockSettings.enabled(this, false); return; }
            refreshToggle(); confirm(ENABLE, "确认开启人脸解锁");
        });
        TextView explanation = new TextView(this);
        explanation.setText("人脸解锁属于便利解锁，照片可能被误识别；敏感操作请使用密码或指纹。");
        root.addView(explanation);
    }
    @Override protected void button(LinearLayout root, String label, Runnable action) {
        Button button = new Button(this); button.setText(label); button.setAllCaps(false);
        int height = Math.round(52 * getResources().getDisplayMetrics().density);
        TypedValue accent = new TypedValue(); getTheme().resolveAttribute(android.R.attr.colorAccent, accent, true);
        GradientDrawable normal = new GradientDrawable(); normal.setCornerRadius(height / 2f); normal.setColor(accent.data);
        GradientDrawable pressed = new GradientDrawable(); pressed.setCornerRadius(height / 2f);
        pressed.setColor((accent.data & 0x00ffffff) | 0xcc000000);
        StateListDrawable background = new StateListDrawable();
        background.addState(new int[]{android.R.attr.state_pressed}, pressed);
        background.addState(new int[]{}, normal); button.setBackground(background);
        boolean dark = (getResources().getConfiguration().uiMode & android.content.res.Configuration.UI_MODE_NIGHT_MASK)
                == android.content.res.Configuration.UI_MODE_NIGHT_YES;
        button.setTextColor(android.os.Build.VERSION.SDK_INT >= 31
                ? getColor(dark ? android.R.color.system_accent1_800 : android.R.color.system_accent1_0)
                : android.graphics.Color.WHITE);
        button.setOnClickListener(view -> action.run());
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, height);
        params.topMargin = Math.round(6 * getResources().getDisplayMetrics().density);
        root.addView(button, params);
    }
    private void refreshToggle() {
        if (toggle == null) return;
        refreshing = true; toggle.setChecked(FaceUnlockSettings.enabled(this)); refreshing = false;
    }
    private void confirm(int operation, String title) {
        if (pending != 0) return;
        Intent intent = getSystemService(KeyguardManager.class).createConfirmDeviceCredentialIntent(
                title, "请输入锁屏密码以继续");
        if (intent == null) { message("请先设置锁屏密码"); return; }
        pending = operation; startActivityForResult(intent, operation);
    }
    @Override protected void requestEnrollment() {
        FaceUnlockSettings.enabled(this, false); refreshToggle(); super.requestEnrollment();
    }
    @Override protected void requestDelete() { confirm(DELETE, "确认删除已录入人脸"); }
    @Override protected void onResume() { super.onResume(); refreshToggle(); }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != pending || pending == 0) return;
        pending = 0;
        if (result != RESULT_OK) { message("密码确认已取消"); return; }
        if (request == DELETE) {
            FaceUnlockSettings.enabled(this, false); refreshToggle(); super.requestDelete();
        } else if (request == ENABLE) {
            float[][] samples = null;
            try {
                samples = store.load();
                if (samples == null) { message("请先录入人脸"); return; }
                // The agent may have been unbound during credential confirmation.
                // This successful system credential result resets its own lockout.
                if (!getSharedPreferences(FaceUnlockSettings.PREFS, MODE_PRIVATE).edit()
                        .putInt("failed_attempts", 0).commit())
                    throw new IllegalStateException("Lockout reset failed");
                FaceUnlockSettings.enabled(this, true); message("人脸解锁已开启");
            } catch (Exception failure) { message("无法开启，请重新录入人脸"); }
            finally {
                if (samples != null) for (float[] sample : samples) java.util.Arrays.fill(sample, 0);
                refreshToggle();
            }
        }
    }
}
