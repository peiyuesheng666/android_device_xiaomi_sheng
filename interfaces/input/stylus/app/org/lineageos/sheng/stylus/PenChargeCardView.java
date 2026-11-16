// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.LinearLayout;
import android.widget.TextView;
import com.android.internal.graphics.drawable.BackgroundBlurDrawable;
import java.util.function.Consumer;
import org.lineageos.sheng.pen.charge.PenUiMotion;
import org.lineageos.sheng.pen.charge.StockPenArtwork;
import org.lineageos.sheng.pen.charge.WavyChargeView;

/** Compact native glass card with theme-tinted OEM artwork and a wave charge indicator. */
final class PenChargeCardView extends LinearLayout {
    private final TextView state, percentage;
    private final WavyChargeView battery;
    private final boolean dark;
    private final Runnable dismiss;
    private final GradientDrawable surface=new GradientDrawable();
    private final WindowManager windows;
    private BackgroundBlurDrawable blur;
    private final Consumer<Boolean> blurChanges=this::updateBlur;

    PenChargeCardView(Context context,boolean dark,Runnable dismiss) {
        super(context);this.dark=dark;this.dismiss=dismiss;
        windows=context.getSystemService(WindowManager.class);
        int ink=dark?0xFFF0F1F4:0xFF24272D, muted=dark?0xFFC2C6CE:0xFF555B65;
        setOrientation(HORIZONTAL);setGravity(Gravity.CENTER_VERTICAL);
        setPadding(dp(12),dp(9),dp(12),dp(9));
        setMinimumHeight(dp(50));setElevation(dp(4));setFocusable(true);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);
        surface.setCornerRadius(dp(18));surface.setStroke(dp(1),dark?0x30FFFFFF:0x55FFFFFF);
        setBackground(surface);updateBlur(false);
        LayoutParams artwork=new LayoutParams(dp(28),dp(28));artwork.rightMargin=dp(10);
        addView(new StockPenArtwork(context,ink,true),artwork);
        LinearLayout words=new LinearLayout(context);words.setOrientation(VERTICAL);
        LinearLayout header=new LinearLayout(context);header.setGravity(Gravity.CENTER_VERTICAL);
        header.setBaselineAligned(false);
        state=label(12,muted);state.setSingleLine(false);state.setMaxLines(3);
        header.addView(state,new LayoutParams(0,-2,1));
        percentage=label(13,ink);percentage.setGravity(Gravity.END|Gravity.CENTER_VERTICAL);
        percentage.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
        LayoutParams number=new LayoutParams(-2,-2);number.leftMargin=dp(8);header.addView(percentage,number);
        words.addView(header,new LayoutParams(-1,-2));
        battery=new WavyChargeView(context,dark?0xFFD0DAF3:0xFF4B607F,dark?0x557F8898:0x55798291);
        LayoutParams meter=new LayoutParams(-1,dp(12));meter.topMargin=dp(3);words.addView(battery,meter);
        addView(words,new LayoutParams(0,-2,1));
    }
    private void updateBlur(boolean enabled) {
        if(blur!=null)blur.setBlurRadius(enabled?dp(24):0);
        surface.setColor(dark?(enabled?0xA31D2026:0xE61D2026):(enabled?0xA3DDE2E9:0xE6DDE2E9));
    }
    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        blur=getViewRootImpl().createBackgroundBlurDrawable();blur.setCornerRadius(dp(18));
        setBackground(new LayerDrawable(new Drawable[]{blur,surface}));
        windows.addCrossWindowBlurEnabledListener(getContext().getMainExecutor(),blurChanges);
        updateBlur(windows.isCrossWindowBlurEnabled());
    }
    @Override protected void onDetachedFromWindow() {
        windows.removeCrossWindowBlurEnabledListener(blurChanges);
        if(blur!=null)blur.setVisible(false,false);
        blur=null;setBackground(surface);super.onDetachedFromWindow();
    }
    void update(String name,String status,int level,boolean chargingOrFull) {
        PenUiMotion.setText(state,status);
        String value=level<0?"—":level+"%";PenUiMotion.setText(percentage,value);
        percentage.setVisibility(level<0?GONE:VISIBLE);
        battery.setVisibility(level<0?GONE:VISIBLE);
        battery.setLevel(level,chargingOrFull);setContentDescription(name+", "+status+", "+value);
    }
    @Override public void onInitializeAccessibilityNodeInfo(AccessibilityNodeInfo info) {
        super.onInitializeAccessibilityNodeInfo(info);info.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_DISMISS);
    }
    @Override public boolean performAccessibilityAction(int action,Bundle arguments) {
        if(action==AccessibilityNodeInfo.ACTION_DISMISS){dismiss.run();return true;}
        return super.performAccessibilityAction(action,arguments);
    }
    private TextView label(int size,int color) {
        TextView view=new TextView(getContext());view.setTextSize(size);view.setTextColor(color);
        view.setSingleLine(true);view.setEllipsize(TextUtils.TruncateAt.END);view.setFontFeatureSettings("tnum");
        view.setIncludeFontPadding(false);
        view.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);return view;
    }
    private int dp(float value){return Math.round(value*getResources().getDisplayMetrics().density);}
}
