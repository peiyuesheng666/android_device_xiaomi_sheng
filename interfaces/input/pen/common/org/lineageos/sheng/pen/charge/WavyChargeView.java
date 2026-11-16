// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.charge;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.View;
import android.view.animation.LinearInterpolator;
import android.view.animation.PathInterpolator;

/** A rounded wave progress indicator; motion never changes the measured battery level. */
public final class WavyChargeView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path wave = new Path();
    private final int activeColor, trackColor;
    private int level = -1;
    private boolean charging;
    private float progress, phase;
    private ValueAnimator fillAnimator, waveAnimator;

    public WavyChargeView(Context context, int activeColor, int trackColor) {
        super(context); this.activeColor=activeColor; this.trackColor=trackColor;
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        paint.setStyle(Paint.Style.STROKE); paint.setStrokeCap(Paint.Cap.ROUND);
        paint.setStrokeJoin(Paint.Join.ROUND);
    }

    public void setLevel(int next, boolean isCharging) {
        next=next < 0 ? -1 : Math.min(100,next); charging=isCharging;
        if(next != level) {
            level=next;
            if(fillAnimator!=null)fillAnimator.cancel();
            float end=level < 0 ? 0 : level/100f;
            if(!isAttachedToWindow() || !ValueAnimator.areAnimatorsEnabled() || level<0)progress=end;
            else {
                fillAnimator=ValueAnimator.ofFloat(progress,end); fillAnimator.setDuration(360);
                fillAnimator.setInterpolator(new PathInterpolator(.2f,0f,0f,1f));
                fillAnimator.addUpdateListener(a -> {progress=(float)a.getAnimatedValue();invalidate();});
                fillAnimator.start();
            }
        }
        updateMotion(); invalidate();
    }

    private void updateMotion() {
        boolean move=charging && level>=0 && level<100 && isAttachedToWindow()
                && isShown() && getWindowVisibility()==VISIBLE && ValueAnimator.areAnimatorsEnabled();
        if(move && waveAnimator==null) {
            waveAnimator=ValueAnimator.ofFloat(0f,1f); waveAnimator.setDuration(2400);
            waveAnimator.setRepeatCount(ValueAnimator.INFINITE);
            waveAnimator.setInterpolator(new LinearInterpolator());
            waveAnimator.addUpdateListener(a -> {phase=(float)a.getAnimatedValue();invalidate();});
            waveAnimator.start();
        } else if(!move && waveAnimator!=null) {waveAnimator.cancel();waveAnimator=null;}
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float inset=dp(3), width=Math.max(0,getWidth()-2*inset), mid=getHeight()/2f;
        float end=width*Math.max(0,Math.min(1,progress));
        paint.setColor(trackColor);paint.setStrokeWidth(dp(2));
        if(end<width)canvas.drawLine(inset+Math.min(width,end+dp(5)),mid,inset+width,mid,paint);
        if(end<=0)return;
        paint.setColor(activeColor);paint.setStrokeWidth(dp(3));wave.rewind();
        wave.moveTo(inset,mid);
        float step=Math.max(1,dp(1));
        for(float x=step;x<end;x+=step) {
            float envelope=Math.max(0,Math.min(1,Math.min(x,end-x)/dp(10)));
            float y=mid+(float)Math.sin((x/dp(18)-phase)*Math.PI*2)*dp(2.2f)*envelope;
            wave.lineTo(inset+x,y);
        }
        wave.lineTo(inset+end,mid);canvas.drawPath(wave,paint);
        paint.setStyle(Paint.Style.FILL);canvas.drawCircle(inset+end,mid,dp(2.5f),paint);
        paint.setStyle(Paint.Style.STROKE);
    }
    @Override protected void onAttachedToWindow() {super.onAttachedToWindow();updateMotion();}
    @Override protected void onVisibilityChanged(View view,int visibility) {super.onVisibilityChanged(view,visibility);updateMotion();}
    @Override protected void onWindowVisibilityChanged(int visibility) {super.onWindowVisibilityChanged(visibility);updateMotion();}
    @Override protected void onDetachedFromWindow() {
        if(fillAnimator!=null)fillAnimator.cancel();
        if(waveAnimator!=null){waveAnimator.cancel();waveAnimator=null;}
        super.onDetachedFromWindow();
    }
    private float dp(float value) {return value*getResources().getDisplayMetrics().density;}
}
