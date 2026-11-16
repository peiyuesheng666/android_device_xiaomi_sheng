// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.app.Activity;
import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.content.res.ColorStateList;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.lineageos.sheng.pen.charge.ChargeStatus;
import org.lineageos.sheng.pen.charge.PenUiMotion;
import org.lineageos.sheng.pen.charge.StockPenArtwork;
import org.lineageos.sheng.pen.charge.WavyChargeView;

/** Native pen page with OEM vector artwork and shared, lifecycle-bound charge motion. */
final class PenPageView extends ScrollView {
    static final class Field {
        final TextView view;
        final Runnable changed;
        final boolean numeric;
        private CharSequence summary;
        Field(TextView view) { this(view, () -> {}, false); }
        Field(TextView view, Runnable changed, boolean numeric) {
            this.view = view; this.changed = changed; this.numeric = numeric; this.summary = view.getText();
        }
        void setSummary(int resource) { setSummary(view.getContext().getString(resource)); }
        void setSummary(CharSequence text) {
            if (android.text.TextUtils.equals(summary, text)) return;
            summary = text;
            PenUiMotion.setText(view, numeric && !text.toString().matches("[0-9]{1,3}%") ? "—" : text);
            changed.run();
        }
        CharSequence getSummary() { return summary; }
    }

    final Field connection, battery, firmware, software;
    private final LinearLayout content, overview, hero, statistics;
    private final TextView model, charge, manage, refresh;
    private final WavyChargeView wave;
    private int batteryLevel = -1;
    private boolean charging, entered;
    private final boolean dark;
    private final int ink, muted, surface, tint, accent;
    private boolean wide;

    PenPageView(Activity context) {
        super(context);
        dark = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        ink = dark ? 0xFFF0F2F8 : 0xFF202A3C;
        muted = dark ? 0xFFADB8CA : 0xFF657187;
        surface = dark ? 0xFF1C2430 : 0xFFFFFFFF;
        tint = dark ? 0xFF282E46 : 0xFFEBEEFF;
        accent = dark ? 0xFFBCC7FF : 0xFF4F61B8;
        int background = dark ? 0xFF111721 : 0xFFF4F6FA;
        setBackgroundColor(background); setFillViewport(true); setClipToPadding(false);
        setVerticalScrollBarEnabled(false);
        FrameLayout frame = new FrameLayout(context);
        content = new LinearLayout(context); content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(24), dp(12), dp(24), dp(32));
        frame.addView(content, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL));
        addView(frame, new LayoutParams(-1, -1));
        setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets safe = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            setPadding(safe.left, safe.top, safe.right, safe.bottom); return insets;
        });

        LinearLayout toolbar = new LinearLayout(context); toolbar.setGravity(Gravity.CENTER_VERTICAL);
        View back = new BackButton(context); back.setFocusable(true);
        back.setContentDescription(getResources().getString(R.string.back));
        back.setBackground(buttonBackground(surface)); back.setOnClickListener(v -> context.finish());
        toolbar.addView(back, new LinearLayout.LayoutParams(dp(48), dp(48)));
        TextView title = text(getResources().getString(R.string.app_name), 26, ink); title.setPadding(dp(16), 0, 0, 0);
        title.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        toolbar.addView(title); content.addView(toolbar);
        TextView subtitle = text(getResources().getString(R.string.page_subtitle), 14, muted);
        subtitle.setPadding(0, dp(18), 0, dp(22)); content.addView(subtitle);

        overview = new LinearLayout(context); overview.setOrientation(LinearLayout.VERTICAL);
        overview.setBaselineAligned(false);
        hero = card(tint); hero.setMinimumHeight(dp(270));
        TextView tag = text(getResources().getString(R.string.your_pen), 12, accent);
        tag.setLetterSpacing(.08f); hero.addView(tag);
        model = text(getResources().getString(R.string.focus_pen), 27, ink);
        model.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        model.setPadding(0, dp(9), 0, 0); hero.addView(model);
        TextView connectionText = text(getResources().getString(R.string.reading), 14, muted);
        connectionText.setPadding(0, dp(8), 0, 0); hero.addView(connectionText); connection = new Field(connectionText);
        StockPenArtwork drawing = new StockPenArtwork(context, ink, false);
        drawing.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        hero.addView(drawing, new LinearLayout.LayoutParams(-1, dp(143)));

        statistics = card(surface);
        TextView batteryLabel = text(getResources().getString(R.string.battery), 14, muted); statistics.addView(batteryLabel);
        LinearLayout batteryRow = new LinearLayout(context); batteryRow.setGravity(Gravity.CENTER_VERTICAL);
        batteryRow.setBaselineAligned(false);
        TextView percentage = text("—", 46, ink); percentage.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        percentage.setSingleLine(true);
        percentage.setPadding(0, dp(14), 0, dp(8));
        batteryRow.addView(percentage, new LinearLayout.LayoutParams(0, -2, 1));
        wave = new WavyChargeView(context, accent, dark ? 0xFF424B60 : 0xFFD8DFEC);
        battery = new Field(percentage, () -> {
            String value = percentage.getText().toString();
            try { batteryLevel = value.endsWith("%") ? Integer.parseInt(value.substring(0, value.length() - 1)) : -1; }
            catch (NumberFormatException invalid) { batteryLevel = -1; }
            wave.setLevel(batteryLevel, charging);
        }, true);
        statistics.addView(batteryRow);
        LinearLayout.LayoutParams waveParams = new LinearLayout.LayoutParams(-1, dp(20));
        waveParams.topMargin = dp(6); statistics.addView(wave, waveParams);
        charge = text(getResources().getString(R.string.charge_unknown), 15, muted);
        charge.setPadding(0, dp(9), 0, 0); statistics.addView(charge);
        TextView hint = text(getResources().getString(R.string.charge_hint), 12, muted);
        hint.setLineSpacing(dp(3), 1); hint.setPadding(0, dp(13), 0, 0); statistics.addView(hint);
        overview.addView(hero); overview.addView(statistics); content.addView(overview);

        LinearLayout.LayoutParams controlsParams = new LinearLayout.LayoutParams(-1, -2);
        controlsParams.topMargin = dp(18);
        content.addView(new PenControlsSection(context, surface, ink, muted, accent), controlsParams);

        LinearLayout versions = card(surface);
        TextView details = text(getResources().getString(R.string.device_information), 18, ink);
        details.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL)); versions.addView(details);
        firmware = infoRow(versions, R.string.firmware);
        software = infoRow(versions, R.string.software);
        LinearLayout.LayoutParams section = new LinearLayout.LayoutParams(-1, -2); section.topMargin = dp(18);
        content.addView(versions, section);

        LinearLayout actions = new LinearLayout(context); actions.setGravity(Gravity.CENTER_VERTICAL);
        manage = button(getResources().getString(R.string.manage_connection), true);
        refresh = button(getResources().getString(R.string.refresh), false);
        LinearLayout.LayoutParams first = new LinearLayout.LayoutParams(0, -2, 1); first.rightMargin = dp(12);
        actions.addView(manage, first); actions.addView(refresh, new LinearLayout.LayoutParams(0, -2, 1));
        LinearLayout.LayoutParams actionParams = new LinearLayout.LayoutParams(-1, -2); actionParams.topMargin = dp(22);
        content.addView(actions, actionParams);
        layoutOverview(false);
    }

    void setActions(Runnable bluetooth, Runnable reload) {
        manage.setOnClickListener(view -> bluetooth.run()); refresh.setOnClickListener(view -> reload.run());
    }

    void setModel(String name) { PenUiMotion.setText(model, name); }

    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        if (!entered) {
            entered = true;
            for (int i = 0; i < content.getChildCount(); i++)
                PenUiMotion.enter(content.getChildAt(i), Math.min(i * 24, 120));
        }
    }
    @Override protected void onDetachedFromWindow() {
        for (int i = 0; i < content.getChildCount(); i++) {
            View child = content.getChildAt(i); child.animate().cancel(); child.setAlpha(1); child.setTranslationY(0);
        }
        super.onDetachedFromWindow();
    }

    void setCharge(ChargeStatus status) {
        int label;
        switch (status.state) {
            case ACQUIRING: label = R.string.charge_acquiring; break;
            case CHARGING: label = R.string.charging; break;
            case FULL: label = R.string.fully_charged; break;
            case WAITING: label = R.string.charge_attached; break;
            case DETACHED: label = R.string.charge_detached; break;
            case NOT_CHARGING: label = R.string.not_charging; break;
            case MISALIGNED: label = R.string.charge_placement; break;
            default: label = R.string.charge_unknown;
        }
        PenUiMotion.setText(charge, getResources().getString(label));
        charging = status.charging(); wave.setLevel(batteryLevel, charging);
        charge.setTextColor(status.charging() || status.state == ChargeStatus.State.FULL
                ? (dark ? 0xFF86D6AF : 0xFF237A55) : muted);
    }

    @Override protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = MeasureSpec.getSize(widthMeasureSpec);
        FrameLayout.LayoutParams params = (FrameLayout.LayoutParams) content.getLayoutParams();
        params.width = Math.max(1, Math.min(width - getPaddingLeft() - getPaddingRight(), dp(950)));
        boolean nextWide = params.width >= dp(740);
        if (nextWide != wide) layoutOverview(nextWide);
        super.onMeasure(widthMeasureSpec, heightMeasureSpec);
    }

    private void layoutOverview(boolean isWide) {
        wide = isWide; overview.setOrientation(wide ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        LinearLayout.LayoutParams left = new LinearLayout.LayoutParams(wide ? 0 : -1, -2, wide ? 1.15f : 0);
        LinearLayout.LayoutParams right = new LinearLayout.LayoutParams(wide ? 0 : -1, wide ? -1 : -2, wide ? 1 : 0);
        if (wide) { left.rightMargin = dp(18); statistics.setMinimumHeight(dp(270)); }
        else { right.topMargin = dp(18); statistics.setMinimumHeight(0); }
        hero.setLayoutParams(left); statistics.setLayoutParams(right);
    }

    private LinearLayout card(int color) {
        LinearLayout view = new LinearLayout(getContext()); view.setOrientation(LinearLayout.VERTICAL);
        view.setPadding(dp(24), dp(23), dp(24), dp(23)); view.setBackground(round(color, 26)); return view;
    }

    private Field infoRow(LinearLayout parent, int label) {
        LinearLayout row = new LinearLayout(getContext()); row.setGravity(Gravity.CENTER_VERTICAL);
        // Loading text can use a different font baseline than numeric revisions.
        row.setBaselineAligned(false);
        row.setPadding(0, dp(22), 0, dp(2));
        row.addView(text(getResources().getString(label), 14, muted), new LinearLayout.LayoutParams(0, -2, 1));
        TextView value = text("—", 15, ink); value.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        value.setSingleLine(true);
        row.addView(value, new LinearLayout.LayoutParams(-2,
                Math.round(24 * getResources().getDisplayMetrics().scaledDensity)));
        parent.addView(row); return new Field(value);
    }

    private TextView button(String label, boolean primary) {
        TextView view = text(label, 15, primary ? (dark ? 0xFF1C264B : 0xFFFFFFFF) : accent);
        view.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL)); view.setGravity(Gravity.CENTER);
        view.setMinHeight(dp(54)); view.setPadding(dp(10), dp(13), dp(10), dp(13));
        view.setBackground(buttonBackground(primary ? accent : tint)); view.setFocusable(true); return view;
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(getContext()); view.setText(value); view.setTextSize(size);
        view.setTextColor(color); view.setFontFeatureSettings("tnum"); return view;
    }

    private GradientDrawable round(int color, int radius) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color); shape.setCornerRadius(dp(radius)); return shape;
    }

    private RippleDrawable buttonBackground(int color) {
        return new RippleDrawable(ColorStateList.valueOf(dark ? 0x33FFFFFF : 0x22000000), round(color, 18), null);
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private final class BackButton extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        BackButton(Context context) { super(context); }
        @Override public CharSequence getAccessibilityClassName() { return "android.widget.Button"; }
        @Override protected void onDraw(Canvas canvas) {
            float cx = getWidth() / 2f, cy = getHeight() / 2f;
            float direction = getLayoutDirection() == LAYOUT_DIRECTION_RTL ? -1 : 1;
            Path arrow = new Path();
            arrow.moveTo(cx + direction * dp(4), cy - dp(8));
            arrow.lineTo(cx - direction * dp(4), cy);
            arrow.lineTo(cx + direction * dp(4), cy + dp(8));
            paint.setColor(ink); paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(2.2f)); paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND); canvas.drawPath(arrow, paint);
        }
    }

}
