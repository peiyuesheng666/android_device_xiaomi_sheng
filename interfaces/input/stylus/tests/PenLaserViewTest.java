package org.lineageos.sheng.stylus;

import android.content.Context;
import android.graphics.Canvas;
import android.util.Log;

public final class PenLaserViewTest {
    private static int checks;

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }

    private static void circles(PenLaserView view, float x, float y) {
        Canvas canvas = new Canvas();
        view.onDraw(canvas);
        check(canvas.circles.size() == 3, "three visible layers");
        int[] colors = {0x55FF1744, 0xFFFF1744, 0xFFFFFFFF};
        float[] radii = {24, 10, 4};
        for (int index = 0; index < 3; index++) {
            Canvas.Circle circle = canvas.circles.get(index);
            check(circle.x == x && circle.y == y, "display to window mapping");
            check(circle.radius == radii[index], "density-scaled radius");
            check(circle.color == colors[index], "visible pointer colors");
        }
    }

    private static void empty(PenLaserView view) {
        Canvas canvas = new Canvas();
        view.onDraw(canvas);
        check(canvas.circles.isEmpty(), "invalid or cleared position must not draw");
    }

    public static void main(String[] arguments) {
        PenLaserView view = new PenLaserView(new Context());
        view.width = 3048; view.height = 2032;
        empty(view);
        check(Log.messages.isEmpty(), "no success log before actual draw");
        view.position(1400, 900);
        check(Log.messages.isEmpty(), "position update alone is not a rendered frame");
        circles(view, 1400, 900);
        check(Log.messages.stream().filter(message -> message.contains("first draw")).count() == 1,
                "draw success logged after circle commands");
        view.originX = 120; view.originY = 84;
        circles(view, 1280, 816);
        view.clearPosition();
        empty(view);
        view.position(1520, 1020);
        circles(view, 1400, 936);
        check(Log.messages.stream().filter(message -> message.contains("first draw")).count() == 1,
                "hover reentry reuses one view without duplicate first-frame claims");
        view.originX = 0; view.originY = 0; view.width = 2032; view.height = 3048;
        view.position(900, 1400);
        circles(view, 900, 1400);
        view.position(0, 0);
        circles(view, 0, 0);
        view.position(2031, 3047);
        circles(view, 2031, 3047);
        for (float[] point : new float[][]{{-1, 5}, {5, -1}, {2032, 5}, {5, 3048},
                {Float.NaN, 5}, {5, Float.NaN}, {Float.POSITIVE_INFINITY, 5},
                {5, Float.NEGATIVE_INFINITY}}) {
            view.position(point[0], point[1]);
            empty(view);
        }
        view.position(600, 800);
        circles(view, 600, 800);
        view.clearPosition();
        empty(view);
        check(view.invalidations == 16, "every update and clear schedules animation invalidation");
        System.out.println("PASS laser_view_checks=" + checks
                + " canvas=recording_double android_compositor_tested=false hardware_tested=false");
    }
}
