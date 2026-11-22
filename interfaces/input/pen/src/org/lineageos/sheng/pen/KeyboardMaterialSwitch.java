package org.lineageos.sheng.pen;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.drawable.GradientDrawable;
import android.widget.Switch;

/** Native switch semantics with a complete, unclipped Material pill and state icon. */
final class KeyboardMaterialSwitch extends Switch {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float density;
    private int surface, ink, tint, accent;

    KeyboardMaterialSwitch(Context context) {
        super(context);
        density = getResources().getDisplayMetrics().density;
        GradientDrawable track = new GradientDrawable();
        track.setColor(Color.TRANSPARENT);
        track.setSize(Math.round(52 * density), Math.round(32 * density));
        GradientDrawable thumb = new GradientDrawable();
        thumb.setColor(Color.TRANSPARENT);
        thumb.setSize(Math.round(24 * density), Math.round(32 * density));
        setTrackTintList(null);
        setThumbTintList(null);
        setTrackDrawable(track);
        setThumbDrawable(thumb);
        setSwitchMinWidth(Math.round(52 * density));
        setSwitchPadding(Math.round(16 * density));
        setShowText(false);
        setSplitTrack(false);
    }

    void setColors(int surface, int ink, int tint, int accent) {
        this.surface = surface; this.ink = ink; this.tint = tint; this.accent = accent;
        invalidate();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float left = getLayoutDirection() == LAYOUT_DIRECTION_RTL
                ? getPaddingLeft() : getWidth() - getPaddingRight() - 52 * density;
        float top = (getHeight() - 32 * density) / 2f;
        int save = canvas.save();
        canvas.translate(left, top);
        canvas.scale(density, density);
        boolean checked = isChecked();
        paint.setAlpha(255);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(checked ? accent : surface);
        paint.setAlpha(isEnabled() ? 255 : 97);
        canvas.drawRoundRect(0, 0, 52, 32, 16, 16, paint);
        if (!checked) {
            paint.setColor(ink); paint.setAlpha(isEnabled() ? 140 : 53);
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(2);
            canvas.drawRoundRect(1, 1, 51, 31, 15, 15, paint);
        }
        boolean right = checked != (getLayoutDirection() == LAYOUT_DIRECTION_RTL);
        float cx = right ? 36 : 16;
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(checked ? tint : ink);
        paint.setAlpha(isEnabled() ? 255 : 97);
        canvas.drawCircle(cx, 16, 12, paint);
        paint.setColor(checked ? accent : surface);
        paint.setAlpha(isEnabled() ? 255 : 97);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(2); paint.setStrokeCap(Paint.Cap.ROUND);
        paint.setStrokeJoin(Paint.Join.ROUND);
        Path icon = new Path();
        if (checked) {
            icon.moveTo(cx - 5, 16); icon.lineTo(cx - 1, 20); icon.lineTo(cx + 5, 13);
        } else {
            icon.moveTo(cx - 4, 12); icon.lineTo(cx + 4, 20);
            icon.moveTo(cx + 4, 12); icon.lineTo(cx - 4, 20);
        }
        canvas.drawPath(icon, paint);
        canvas.restoreToCount(save);
    }
}
