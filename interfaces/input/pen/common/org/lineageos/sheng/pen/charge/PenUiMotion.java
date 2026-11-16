// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.charge;

import android.animation.ValueAnimator;
import android.text.TextUtils;
import android.view.View;
import android.view.animation.PathInterpolator;
import android.widget.TextView;

public final class PenUiMotion {
    private PenUiMotion() {}
    public static void setText(TextView view,CharSequence text) {
        if(TextUtils.equals(view.getText(),text))return;
        view.animate().cancel();view.setText(text);
        if(!view.isAttachedToWindow() || !ValueAnimator.areAnimatorsEnabled()) {
            view.setAlpha(1);view.setTranslationY(0);return;
        }
        view.setAlpha(.65f);view.setTranslationY(2*view.getResources().getDisplayMetrics().density);
        view.animate().alpha(1).translationY(0).setStartDelay(0).setDuration(220)
                .setInterpolator(new PathInterpolator(.2f,0f,0f,1f)).start();
    }
    public static void enter(View view,int delay) {
        if(!ValueAnimator.areAnimatorsEnabled())return;
        view.setAlpha(0);view.setTranslationY(10*view.getResources().getDisplayMetrics().density);
        view.animate().alpha(1).translationY(0).setStartDelay(delay).setDuration(400)
                .setInterpolator(new PathInterpolator(.16f,1f,.3f,1f)).start();
    }
}
