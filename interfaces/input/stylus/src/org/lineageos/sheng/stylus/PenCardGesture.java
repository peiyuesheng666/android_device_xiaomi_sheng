// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

/** Distinguish an intentional click/downward pull from cancellation and other drags. */
public final class PenCardGesture {
    public enum Result { NONE, OPEN, DISMISS }
    private final float slop, swipe;
    private float x, y, furthest;
    private boolean active;
    public PenCardGesture(float slop, float swipe) { this.slop=slop;this.swipe=swipe; }
    public void down(float x,float y) { this.x=x;this.y=y;furthest=0;active=true; }
    public void move(float x,float y) { if(active)furthest=Math.max(furthest,Math.max(Math.abs(x-this.x),Math.abs(y-this.y))); }
    public void cancel() { active=false; }
    public Result up(float x,float y) {
        if(!active)return Result.NONE;
        move(x,y);active=false;
        float dx=x-this.x,dy=y-this.y;
        if(Math.abs(dy)>=swipe && Math.abs(dy)>Math.abs(dx))return dy>0?Result.OPEN:Result.DISMISS;
        return furthest<=slop?Result.OPEN:Result.NONE;
    }
}
