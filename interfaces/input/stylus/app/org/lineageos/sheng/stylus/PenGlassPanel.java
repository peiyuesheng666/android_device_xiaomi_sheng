// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.content.Context;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.view.WindowManager;
import android.widget.LinearLayout;
import com.android.internal.graphics.drawable.BackgroundBlurDrawable;
import java.util.function.Consumer;

/** The shortcut palette uses the charging card's glass surface and blur lifecycle. */
final class PenGlassPanel extends LinearLayout {
    private final boolean dark;
    private final WindowManager windows;
    private final GradientDrawable surface = new GradientDrawable();
    private BackgroundBlurDrawable blur;
    private final Consumer<Boolean> blurChanges = this::updateBlur;
    PenGlassPanel(Context context, boolean dark) {
        super(context);this.dark=dark;windows=context.getSystemService(WindowManager.class);
        surface.setCornerRadius(dp(20));surface.setStroke(dp(1),dark?0x30FFFFFF:0x55FFFFFF);
        setBackground(surface);setElevation(dp(5));updateBlur(false);
    }
    private int dp(float value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private void updateBlur(boolean enabled) {
        if(blur!=null)blur.setBlurRadius(enabled?dp(24):0);
        surface.setColor(dark?(enabled?0xA31D2026:0xE61D2026):(enabled?0xA3DDE2E9:0xE6DDE2E9));
    }
    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();blur=getViewRootImpl().createBackgroundBlurDrawable();blur.setCornerRadius(dp(20));
        setBackground(new LayerDrawable(new Drawable[]{blur,surface}));
        windows.addCrossWindowBlurEnabledListener(getContext().getMainExecutor(),blurChanges);
        updateBlur(windows.isCrossWindowBlurEnabled());
    }
    @Override protected void onDetachedFromWindow() {
        windows.removeCrossWindowBlurEnabledListener(blurChanges);
        if(blur!=null)blur.setVisible(false,false);
        blur=null;setBackground(surface);super.onDetachedFromWindow();
    }
}
