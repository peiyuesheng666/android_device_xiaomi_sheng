/* SPDX-License-Identifier: Apache-2.0 */
package com.android.systemui.sheng;

import android.content.Context;
import android.graphics.Point;
import android.graphics.PointF;
import android.util.DisplayMetrics;
import android.util.RotationUtils;
import android.view.Display;
import android.view.Surface;

import com.android.systemui.res.R;

/** Shared physical power-button geometry for sheng's naturally landscape display. */
public final class ShengPowerButtonGeometry {
    private ShengPowerButtonGeometry() {}

    /** Position in the current display rotation; the native power button is on the left edge. */
    public static final class Position {
        public final float x;
        public final float y;
        public final int rotation;

        private Position(PointF point, int rotation) {
            this.x = point.x;
            this.y = point.y;
            this.rotation = rotation;
        }

        public boolean isOnVerticalEdge() {
            return rotation == Surface.ROTATION_0 || rotation == Surface.ROTATION_180;
        }
    }

    /**
     * Maps the native left-edge button into a view in the display's current rotation.
     * nativeY is the existing resource/constructor value, measured down the native left edge.
     * offscreenFraction is zero for wake origins and positive for the original reveal effect.
     * No panel size or unmeasured button coordinate is hard-coded here.
     */
    public static Position position(Context context, float currentWidth, float currentHeight,
            float nativeY, float offscreenFraction) {
        final Display display = context.getDisplay();
        final int rotation = display == null ? Surface.ROTATION_0 : display.getRotation();
        final boolean sideways =
                rotation == Surface.ROTATION_90 || rotation == Surface.ROTATION_270;
        final float nativeWidth = Math.max(0f, sideways ? currentHeight : currentWidth);
        final float nativeHeight = Math.max(0f, sideways ? currentWidth : currentHeight);
        final float buttonY = Math.max(0f, Math.min(nativeY, nativeHeight));
        final PointF point = new PointF(-nativeWidth * offscreenFraction, buttonY);
        // Use the framework's physical-to-logical CCW rotation convention for all four rotations.
        RotationUtils.rotatePointF(point, rotation, nativeWidth, nativeHeight);
        return new Position(point, rotation);
    }

    /** The same physical button position, directly on the screen edge, for wallpaper wake events. */
    @SuppressWarnings("deprecation")
    public static Point wakeOrigin(Context context) {
        final Point size = new Point();
        final Display display = context.getDisplay();
        if (display != null) {
            display.getRealSize(size);
        } else {
            final DisplayMetrics metrics = context.getResources().getDisplayMetrics();
            size.set(metrics.widthPixels, metrics.heightPixels);
        }
        final float nativeY = context.getResources().getDimension(
                R.dimen.physical_power_button_center_screen_location_y);
        final Position position = position(context, size.x, size.y, nativeY, 0f);
        return new Point(Math.round(position.x), Math.round(position.y));
    }
}
