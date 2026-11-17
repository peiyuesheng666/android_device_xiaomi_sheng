package org.lineageos.sheng.stylus;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.util.Log;
import android.view.View;

final class PenLaserView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int[] origin = new int[2];
    private float screenX, screenY;
    private boolean positioned, drawn;

    PenLaserView(Context context) {
        super(context);
    }

    void position(float x, float y) {
        positioned = Float.isFinite(x) && Float.isFinite(y);
        screenX = x; screenY = y;
        postInvalidateOnAnimation();
    }

    void clearPosition() {
        positioned = false;
        postInvalidateOnAnimation();
    }

    @Override protected void onDraw(Canvas canvas) {
        if (!positioned) return;
        getLocationOnScreen(origin);
        float x = screenX - origin[0], y = screenY - origin[1];
        if (x < 0 || y < 0 || x >= getWidth() || y >= getHeight()) {
            if (!drawn) Log.w("ShengPenButtons", "Laser position outside window: screen="
                    + screenX + "," + screenY + " origin=" + origin[0] + "," + origin[1]
                    + " size=" + getWidth() + "x" + getHeight());
            return;
        }
        float density = getResources().getDisplayMetrics().density;
        paint.setColor(0x55FF1744);
        canvas.drawCircle(x, y, 12 * density, paint);
        paint.setColor(0xFFFF1744);
        canvas.drawCircle(x, y, 5 * density, paint);
        paint.setColor(0xFFFFFFFF);
        canvas.drawCircle(x, y, 2 * density, paint);
        if (!drawn) {
            drawn = true;
            Log.i("ShengPenButtons", "Laser first draw: local=" + x + "," + y
                    + " size=" + getWidth() + "x" + getHeight());
        }
    }
}
