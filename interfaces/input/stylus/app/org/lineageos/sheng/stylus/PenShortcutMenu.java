// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.content.Context;
import android.app.ActivityManager;
import android.content.pm.LauncherActivityInfo;
import android.content.res.Configuration;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Handler;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.animation.PathInterpolator;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.function.Consumer;
import org.lineageos.sheng.pen.controls.PenControls.Action;
import org.lineageos.sheng.pen.controls.PenMenuEntry;
import org.lineageos.sheng.pen.controls.PenMenuApps;

/** Original small pen palette. No notification, screenshot preview or copied assets. */
final class PenShortcutMenu {
    private final Context context;
    private final Handler main;
    private final Consumer<PenMenuEntry> selected;
    private final WindowManager windows;
    private final boolean dark, chinese;
    private final int ink, muted, surface, accent, tile;
    private LinearLayout root;
    private final Runnable timeout = this::hide;

    PenShortcutMenu(Context context, Handler main, Consumer<PenMenuEntry> selected) {
        this.context = context; this.main = main; this.selected = selected;
        windows = context.getSystemService(WindowManager.class);
        dark = (context.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        chinese = context.getResources().getConfiguration().getLocales().get(0).getLanguage().equals("zh");
        ink = context.getColor(dark ? android.R.color.system_neutral1_50 : android.R.color.system_neutral1_900);
        muted = context.getColor(dark ? android.R.color.system_neutral2_200 : android.R.color.system_neutral2_600);
        surface = context.getColor(dark ? android.R.color.system_neutral1_900 : android.R.color.system_neutral1_50);
        accent = context.getColor(dark ? android.R.color.system_accent1_200 : android.R.color.system_accent1_600);
        tile = context.getColor(dark ? android.R.color.system_accent1_800 : android.R.color.system_accent1_100);
    }
    void toggle(PenMenuEntry[] actions, float x, float y) {
        if (root != null) { hide(); return; }
        LinearLayout panel = new PenGlassPanel(context, dark); panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(11), dp(12), dp(12));
        LinearLayout heading = new LinearLayout(context); heading.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = text(chinese ? "快捷菜单" : "Pen shortcuts", 14, ink);
        title.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        heading.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        TextView edit = text(chinese ? "编辑" : "Edit", 12, ink);
        edit.setGravity(Gravity.CENTER);edit.setContentDescription(chinese?"自定义快捷菜单":"Customize pen menu");
        edit.setOnClickListener(v->{hide();selected.accept(PenMenuEntry.operation(Action.SETTINGS));});
        heading.addView(edit,new LinearLayout.LayoutParams(dp(48),dp(32)));
        panel.addView(heading);
        for (int start = 0; start < actions.length; start += 3) {
            LinearLayout row = new LinearLayout(context); row.setBaselineAligned(false);
            for (int column = 0; column < 3; column++) {
                int index = start + column;
                LinearLayout.LayoutParams itemParams = new LinearLayout.LayoutParams(0, -2, 1);
                itemParams.topMargin = dp(8);
                if (column > 0) itemParams.leftMargin = dp(6);
                if (index >= actions.length) { row.addView(new View(context), itemParams); continue; }
                PenMenuEntry entry = actions[index];
                Action action = entry.action;
                int user = ActivityManager.getCurrentUser();
                LinearLayout item = new LinearLayout(context); item.setOrientation(LinearLayout.VERTICAL);
                item.setGravity(Gravity.CENTER); item.setFocusable(true);item.setMinimumHeight(dp(72));
                item.setPadding(dp(3),dp(8),dp(3),dp(8));
                StateListDrawable feedback=new StateListDrawable();
                feedback.addState(new int[]{android.R.attr.state_pressed},round(dark?0x38FFFFFF:0x28000000,14));
                feedback.addState(new int[]{android.R.attr.state_focused},round(dark?0x30FFFFFF:0x20000000,14));
                feedback.addState(new int[]{},round(dark?0x16FFFFFF:0x16000000,14));
                feedback.setEnterFadeDuration(70);feedback.setExitFadeDuration(140);item.setBackground(feedback);
                if(action!=null)item.addView(new Icon(context,action),new LinearLayout.LayoutParams(dp(24),dp(24)));
                else {
                    LauncherActivityInfo app=PenMenuApps.resolve(context,entry,user);
                    ImageView icon=new ImageView(context);icon.setScaleType(ImageView.ScaleType.FIT_CENTER);
                    icon.setImageDrawable(app==null?context.getPackageManager().getDefaultActivityIcon():app.getBadgedIcon(0));
                    icon.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                    item.addView(icon,new LinearLayout.LayoutParams(dp(26),dp(26)));
                }
                String name=PenMenuApps.title(context,entry,user,chinese);
                TextView label = text(name, 11, ink); label.setGravity(Gravity.CENTER);
                label.setPadding(0, dp(6), 0, 0); label.setMaxLines(2);label.setEllipsize(android.text.TextUtils.TruncateAt.END);item.addView(label);
                item.setContentDescription(name);
                item.setOnClickListener(v -> { hide(); main.postDelayed(() -> selected.accept(entry), 120); });
                row.addView(item, itemParams);
            }
            panel.addView(row);
        }
        WindowManager.LayoutParams p = new WindowManager.LayoutParams();
        p.type = WindowManager.LayoutParams.TYPE_SYSTEM_DIALOG;
        p.flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                | WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED;
        p.format = PixelFormat.TRANSLUCENT; p.gravity = Gravity.TOP | Gravity.LEFT;
        android.graphics.Rect bounds = windows.getCurrentWindowMetrics().getBounds();
        android.graphics.Insets safe = windows.getCurrentWindowMetrics().getWindowInsets()
                .getInsetsIgnoringVisibility(android.view.WindowInsets.Type.systemBars()
                        | android.view.WindowInsets.Type.displayCutout());
        p.width = Math.min(dp(284), bounds.width() - safe.left - safe.right - dp(32));
        p.height = WindowManager.LayoutParams.WRAP_CONTENT;
        panel.measure(View.MeasureSpec.makeMeasureSpec(p.width, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
        int left = x >= 0 ? (int) x + dp(24) : bounds.width() - p.width - dp(32);
        int top = y >= 0 ? (int) y - panel.getMeasuredHeight() / 2 : bounds.height() / 2 - panel.getMeasuredHeight() / 2;
        p.x = Math.max(safe.left + dp(12), Math.min(left, bounds.width() - safe.right - p.width - dp(12)));
        p.y = Math.max(safe.top + dp(12), Math.min(top, bounds.height() - safe.bottom - panel.getMeasuredHeight() - dp(12)));
        p.setTitle("Sheng pen shortcuts");
        panel.setOnTouchListener((view, event) -> {
            if (event.getActionMasked() == MotionEvent.ACTION_OUTSIDE) { hide(); return true; }
            return false;
        });
        root = panel;
        try {
            windows.addView(panel, p);
            panel.setAlpha(0); panel.setScaleX(.93f); panel.setScaleY(.93f);
            panel.animate().alpha(1).scaleX(1).scaleY(1).setDuration(280)
                    .setInterpolator(new PathInterpolator(.16f,1f,.3f,1f)).start();
            Log.i("ShengPenButtons","Shortcut menu shown items="+actions.length);
            main.postDelayed(timeout, 8000);
        } catch (RuntimeException error) { root = null; throw error; }
    }
    void hide() {
        main.removeCallbacks(timeout);
        LinearLayout old = root; root = null;
        if (old == null) return;
        Log.i("ShengPenButtons","Shortcut menu hidden");
        old.animate().cancel();
        // Remove the touch target immediately; animations cannot trap a later tap.
        try { windows.removeViewImmediate(old); } catch (IllegalArgumentException detached) { }
    }
    private int dp(float value) { return Math.round(value * context.getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size, int color) {
        TextView view = new TextView(context); view.setText(value); view.setTextSize(size);
        view.setTextColor(color); view.setIncludeFontPadding(false); return view;
    }
    private GradientDrawable round(int color, int radius) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color); shape.setCornerRadius(dp(radius)); return shape;
    }
    private final class Icon extends View {
        private final Action action;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        Icon(Context context, Action action) { super(context); this.action = action; setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO); }
        @Override protected void onDraw(Canvas canvas) {
            canvas.save(); canvas.scale(getWidth() / 28f, getHeight() / 28f);
            paint.setColor(accent); paint.setStrokeWidth(1.9f); paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND); paint.setStyle(Paint.Style.STROKE);
            Path path = new Path();
            switch (action) {
                case BACK:
                    path.moveTo(15, 5); path.lineTo(6, 14); path.lineTo(15, 23);
                    canvas.drawPath(path, paint); canvas.drawLine(6, 14, 24, 14, paint); break;
                case HOME:
                    path.moveTo(3, 13); path.lineTo(14, 4); path.lineTo(25, 13);
                    path.moveTo(6, 11); path.lineTo(6, 24); path.lineTo(22, 24); path.lineTo(22, 11);
                    canvas.drawPath(path, paint); break;
                case RECENTS:
                    canvas.drawRoundRect(3, 6, 15, 22, 3, 3, paint); canvas.drawRoundRect(19, 6, 25, 22, 2, 2, paint); break;
                case MEDIA:
                    path.moveTo(5, 5); path.lineTo(16, 14); path.lineTo(5, 23); path.close();
                    canvas.drawPath(path, paint); canvas.drawLine(20, 6, 20, 22, paint); canvas.drawLine(25, 6, 25, 22, paint); break;
                case SCREENSHOT:
                    canvas.drawRoundRect(5, 5, 23, 23, 3, 3, paint);
                    canvas.drawLine(2, 9, 9, 9, paint); canvas.drawLine(9, 2, 9, 9, paint);
                    canvas.drawLine(19, 19, 26, 19, paint); canvas.drawLine(19, 19, 19, 26, paint); break;
                case UNDO: case REDO:
                    if (action == Action.REDO) { canvas.translate(28, 0); canvas.scale(-1, 1); }
                    path.moveTo(10, 5); path.lineTo(4, 11); path.lineTo(10, 17);
                    canvas.drawPath(path, paint); canvas.drawArc(5, 10, 25, 26, 195, 220, false, paint); break;
                case ASSISTANT:
                    path.moveTo(14, 2); path.quadTo(15, 12, 26, 14); path.quadTo(15, 16, 14, 26);
                    path.quadTo(12, 16, 2, 14); path.quadTo(12, 12, 14, 2); canvas.drawPath(path, paint); break;
                default:
                    path.moveTo(7, 22); path.lineTo(9, 16); path.lineTo(21, 4); path.lineTo(25, 8);
                    path.lineTo(13, 20); path.close(); canvas.drawPath(path, paint);
                    canvas.drawLine(18, 7, 22, 11, paint); canvas.drawLine(4, 25, 24, 25, paint); break;
            }
            canvas.restore();
        }
    }
}
