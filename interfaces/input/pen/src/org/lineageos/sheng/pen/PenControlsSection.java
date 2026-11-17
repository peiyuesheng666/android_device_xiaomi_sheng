// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.UserHandle;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Set;
import org.lineageos.sheng.pen.controls.PenAppOverrides;
import org.lineageos.sheng.pen.controls.PenMenuApps;
import org.lineageos.sheng.pen.controls.PenControls;
import org.lineageos.sheng.pen.controls.PenControls.Action;
import org.lineageos.sheng.pen.controls.PenControls.Gesture;
import org.lineageos.sheng.pen.controls.PenControlsSettings;
import org.lineageos.sheng.pen.controls.PenMenuEntry;

/** Shortcut choices have a stable layout and do not restart the information query. */
final class PenControlsSection extends LinearLayout {
    private final Activity activity;
    private final boolean zh;
    private final int ink, muted, accent, user;
    private final ArrayList<Runnable> summaries = new ArrayList<>();

    PenControlsSection(Activity activity, int surface, int ink, int muted, int accent) {
        super(activity); this.activity = activity; this.ink = ink; this.muted = muted; this.accent = accent;
        user = UserHandle.myUserId();
        zh = getResources().getConfiguration().getLocales().get(0).getLanguage().equals("zh");
        setOrientation(VERTICAL); setPadding(dp(24), dp(23), dp(24), dp(17));
        GradientDrawable background = new GradientDrawable(); background.setColor(surface); background.setCornerRadius(dp(26));
        setBackground(background);
        TextView title = text(zh ? "按键与手势" : "Buttons and gestures", 18, ink);
        title.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL)); addView(title);
        TextView description = text(zh ? "握压笔身打开常用应用与操作" : "Squeeze the pen to reach your apps and actions", 13, muted);
        description.setPadding(0, dp(9), 0, dp(10)); addView(description);
        for (Gesture gesture : Gesture.values()) {
            if (gesture.longPress()) continue;
            if (gesture == Gesture.SLIDE_UP || gesture == Gesture.SLIDE_DOWN) {
                TextView value = row(gesture.title(zh), null);
                value.setText(gesture == Gesture.SLIDE_UP
                        ? (zh ? "向上滚动" : "Scroll up") : (zh ? "向下滚动" : "Scroll down"));
                continue;
            }
            TextView value = row(gesture.title(zh), () -> chooseAction(gesture));
            summaries.add(() -> value.setText(PenControlsSettings.action(activity, gesture, user).title(zh)));
        }
        TextView menu = row(zh ? "自定义快捷菜单" : "Customize shortcut menu", this::chooseMenu);
        summaries.add(() -> menu.setText(PenMenuEntry.read(PenControlsSettings.read(activity, PenControls.MENU, user)).length
                + (zh ? " 项 · 应用与操作" : " apps / actions")));
        TextView overrides = row(zh ? "全局快捷键屏蔽列表" : "Apps that handle pen buttons", this::chooseAppOverrides);
        summaries.add(() -> overrides.setText(PenAppOverrides.read(
                PenControlsSettings.read(activity, PenControls.APP_OVERRIDES, user)).size()
                + (zh ? " 个应用 · 应用接管按键" : " apps · app controls")));
        TextView overrideHint = text(zh
                ? "选中应用在前台时，停用系统快捷动作，以 F1／F2／F3 兼容键交给应用；请在应用内绑定工具。书写与压感不受影响。"
                : "Selected foreground apps receive F1/F2/F3 instead of global shortcuts. Assign tools in the app. Writing and pressure are unchanged.", 12, muted);
        overrideHint.setPadding(0, dp(6), 0, dp(8)); addView(overrideHint);
        refresh();
    }
    @Override protected void onAttachedToWindow() { super.onAttachedToWindow(); refresh(); }
    private void refresh() { for (Runnable update : summaries) update.run(); }
    private TextView row(String title, Runnable action) {
        LinearLayout row = new LinearLayout(activity); row.setGravity(Gravity.CENTER_VERTICAL); row.setBaselineAligned(false);
        row.setMinimumHeight(dp(64)); row.setPadding(0, dp(12), 0, dp(12)); row.setFocusable(true);
        StateListDrawable states = new StateListDrawable();
        states.addState(new int[]{android.R.attr.state_pressed}, rowFeedback(0x18));
        states.addState(new int[]{android.R.attr.state_focused}, rowFeedback(0x12));
        states.addState(new int[]{}, rowFeedback(0));
        states.setEnterFadeDuration(90); states.setExitFadeDuration(180); row.setBackground(states);
        row.addView(text(title, 15, ink), new LayoutParams(0, -2, 1));
        TextView value = text("", 13, muted); value.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        value.setMaxLines(2); row.addView(value, new LayoutParams(dp(128), -2));
        View arrow = new View(activity) {
            final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            @Override protected void onDraw(Canvas canvas) {
                paint.setColor(muted); paint.setStrokeWidth(dp(1.5f)); paint.setStrokeCap(Paint.Cap.ROUND);
                float x = getWidth() * .65f, y = getHeight() * .5f;
                canvas.drawLine(x - dp(4), y - dp(4), x, y, paint);
                canvas.drawLine(x, y, x - dp(4), y + dp(4), paint);
            }
        };
        arrow.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        if (action != null) {
            row.addView(arrow, new LayoutParams(dp(24), dp(24)));
            row.setOnClickListener(view -> action.run());
        } else {
            row.setFocusable(false);
        }
        addView(row, new LayoutParams(-1, -2));
        return value;
    }
    private void chooseAction(Gesture gesture) {
        Action[] actions = Action.values(); String[] labels = new String[actions.length];
        Action current = PenControlsSettings.action(activity, gesture, user); int checked = 0;
        for (int i = 0; i < actions.length; i++) { labels[i] = actions[i].title(zh); if (actions[i] == current) checked = i; }
        new AlertDialog.Builder(activity).setTitle(gesture.title(zh)).setSingleChoiceItems(labels, checked, (dialog, index) -> {
            save(gesture.key(), actions[index].name()); dialog.dismiss();
        }).setNegativeButton(android.R.string.cancel, null).show();
    }
    private GradientDrawable rowFeedback(int alpha) {
        GradientDrawable background = new GradientDrawable();
        background.setCornerRadius(dp(12)); background.setColor((accent & 0x00FFFFFF) | (alpha << 24));
        return background;
    }
    private void chooseMenu() {
        new PenMenuEditor(activity, zh, this::refresh).show();
    }
    private void chooseAppOverrides() {
        Set<String> selected = PenAppOverrides.read(PenControlsSettings.read(activity, PenControls.APP_OVERRIDES, user));
        LinkedHashMap<String, String> apps = new LinkedHashMap<>();
        try {
            for (android.content.pm.LauncherActivityInfo info : PenMenuApps.list(activity, user))
                apps.putIfAbsent(info.getComponentName().getPackageName(), info.getLabel().toString());
        } catch (RuntimeException error) {
            Toast.makeText(activity, zh ? "暂时无法读取应用列表" : "Could not load apps", Toast.LENGTH_SHORT).show();
            return;
        }
        for (String name : selected) apps.putIfAbsent(name, name);
        String[] packages = apps.keySet().toArray(new String[0]);
        String[] labels = new String[packages.length];
        boolean[] checked = new boolean[packages.length];
        for (int index = 0; index < packages.length; index++) {
            labels[index] = apps.get(packages[index]) + "\n" + packages[index];
            checked[index] = selected.contains(packages[index]);
        }
        new AlertDialog.Builder(activity).setTitle(zh ? "全局快捷键屏蔽列表" : "Apps that handle pen buttons")
                .setMultiChoiceItems(labels, checked, (dialog, index, enabled) -> {
                    if (enabled) selected.add(packages[index]); else selected.remove(packages[index]);
                }).setPositiveButton(android.R.string.ok, (dialog, which) ->
                    save(PenControls.APP_OVERRIDES, PenAppOverrides.write(selected)))
                .setNegativeButton(android.R.string.cancel, null).show();
    }
    private void save(String key, String value) {
        try {
            if (!PenControlsSettings.write(activity, key, value)) throw new IllegalStateException("Settings rejected value");
            refresh();
        } catch (RuntimeException error) {
            Toast.makeText(activity, zh ? "暂时无法保存，请稍后重试" : "Could not save this setting", Toast.LENGTH_SHORT).show();
        }
    }
    private TextView text(String value, int size, int color) {
        TextView view = new TextView(activity); view.setText(value); view.setTextSize(size);
        view.setTextColor(color); view.setIncludeFontPadding(false); return view;
    }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
