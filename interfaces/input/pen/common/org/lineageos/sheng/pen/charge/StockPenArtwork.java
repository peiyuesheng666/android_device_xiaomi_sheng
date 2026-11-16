// OEM path geometry from the supplied Xiaomi Settings.apk; see stock-pen-art.json.
package org.lineageos.sheng.pen.charge;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.util.PathParser;
import android.view.View;

public final class StockPenArtwork extends View {
    private static final String[] COMPACT = {"M6.16,19.382L3.62,20.734C3.424,20.838 3.182,20.802 3.025,20.645C2.868,20.489 2.831,20.248 2.935,20.052L4.28,17.502L6.16,19.382Z", "M17.925,2.517C18.373,2.305 18.893,2.306 19.34,2.518C19.597,2.64 19.833,2.876 20.305,3.348C20.777,3.82 21.013,4.057 21.135,4.314C21.348,4.761 21.349,5.281 21.137,5.728C21.015,5.985 20.781,6.22 20.312,6.69C17.501,9.509 12.003,15.017 10.822,16.175C9.092,17.87 8.355,18.216 8.319,18.232L8.32,18.233L7.002,18.934L4.725,16.658L5.422,15.336L5.421,15.335C5.429,15.318 5.769,14.571 7.479,12.831C8.631,11.659 14.143,6.156 16.963,3.343C17.433,2.874 17.668,2.639 17.925,2.517Z"};
    private static final String[] HERO = {"M24.187,3.492C21.383,4.13 18.638,5.037 13.149,6.852L10.18,7.833H10.578V16.167H10.18L13.149,17.148C18.638,18.963 21.383,19.87 24.187,20.508C26.679,21.074 29.204,21.481 31.747,21.725C34.61,22 37.501,22 43.282,22H307.976C311.337,22 313.017,22 314.3,21.346C315.429,20.771 316.347,19.853 316.922,18.724C317.576,17.441 317.576,15.76 317.576,12.4V11.6C317.576,8.24 317.576,6.56 316.922,5.276C316.347,4.147 315.429,3.229 314.3,2.654C313.017,2 311.337,2 307.976,2H43.282C37.501,2 34.61,2 31.747,2.275C29.204,2.519 26.679,2.926 24.187,3.492ZM8.578,15.637V8.363L6.767,8.962C3.97,9.886 2.572,10.349 2.193,11.04C1.866,11.638 1.866,12.362 2.193,12.96C2.572,13.651 3.97,14.114 6.767,15.038L8.578,15.637Z", "M61,9L95,9A3,3 0,0 1,98 12L98,12A3,3 0,0 1,95 15L61,15A3,3 0,0 1,58 12L58,12A3,3 0,0 1,61 9z"};
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path[] paths=new Path[2];
    private final boolean compact;
    private final int color;
    public StockPenArtwork(Context context,int color,boolean compact) {
        super(context);this.color=color;this.compact=compact;
        String[] data=compact?COMPACT:HERO;
        for(int i=0;i<paths.length;i++) {
            paths[i]=PathParser.createPathFromPathData(data[i]);
            paths[i].setFillType(Path.FillType.EVEN_ODD);
        }
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float vw=compact?24:322, vh=24;
        float scale=Math.min(getWidth()*(compact?.8f:.84f)/vw,getHeight()*.75f/vh);
        canvas.save();canvas.translate(getWidth()/2f,getHeight()/2f);
        if(!compact)canvas.rotate(-10);
        canvas.scale(scale,scale);canvas.translate(-vw/2,-vh/2);
        paint.setColor(color);canvas.drawPath(paths[0],paint);
        if(!compact)paint.setAlpha(100);
        canvas.drawPath(paths[1],paint);paint.setAlpha(255);canvas.restore();
    }
}
