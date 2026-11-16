// SPDX-License-Identifier: Apache-2.0
package com.xiaomi.sheng.touch;

import android.app.ActivityManager;
import android.app.Application;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.database.ContentObserver;
import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.PowerManager;
import android.os.UserHandle;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;

/** Keeps the standard Android switch synchronized through the stock THP V2 ABI. */
public final class ShengTouchApplication extends Application {
    private static final String TAG = "ShengTouch";
    private static final String KEY = "double_tap_to_wake";
    private static final int MAX_RETRIES = 4;
    private static final int APPLIED = 0;
    private static final int INVALID = 2;

    private final Handler mMain = new Handler(Looper.getMainLooper());
    private Handler mWorker;
    private DisplayManager mDisplays;
    private PowerManager mPower;
    private long mGeneration;
    private boolean mObservedAwake;

    private static native long nativeInvalidate();
    private static native int nativeApply(int value, long generation);

    @Override
    public void onCreate() {
        super.onCreate();
        try {
            System.loadLibrary("sheng_touch_jni");
        } catch (UnsatisfiedLinkError error) {
            Log.e(TAG, "Native touch backend unavailable; no controller changes", error);
            return;
        }
        mDisplays = getSystemService(DisplayManager.class);
        mPower = getSystemService(PowerManager.class);
        HandlerThread thread = new HandlerThread("ShengTouchControl");
        thread.start();
        mWorker = new Handler(thread.getLooper());

        getContentResolver().registerContentObserver(Settings.Secure.getUriFor(KEY), false,
                new ContentObserver(mMain) {
                    @Override
                    public void onChange(boolean selfChange) { reconcile(); }
                }, UserHandle.USER_ALL);
        mDisplays.registerDisplayListener(new DisplayManager.DisplayListener() {
            @Override
            public void onDisplayAdded(int id) { if (id == Display.DEFAULT_DISPLAY) displayChanged(); }
            @Override
            public void onDisplayRemoved(int id) { if (id == Display.DEFAULT_DISPLAY) displayChanged(); }
            @Override
            public void onDisplayChanged(int id) { if (id == Display.DEFAULT_DISPLAY) displayChanged(); }
        }, mMain);

        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        filter.addAction(Intent.ACTION_USER_SWITCHED);
        filter.addAction(Intent.ACTION_USER_UNLOCKED);
        filter.addAction(Intent.ACTION_BOOT_COMPLETED);
        registerReceiver(new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (Intent.ACTION_SCREEN_ON.equals(intent.getAction()) ||
                        Intent.ACTION_SCREEN_OFF.equals(intent.getAction())) {
                    displayChanged();
                } else {
                    reconcile();
                }
            }
        }, filter, Context.RECEIVER_NOT_EXPORTED);
        reconcile();
    }

    private boolean awake() {
        Display display = mDisplays.getDisplay(Display.DEFAULT_DISPLAY);
        return display != null && display.getState() == Display.STATE_ON && mPower.isInteractive();
    }

    private void displayChanged() {
        // Refresh-rate, brightness and geometry changes are not wake transitions.
        boolean current = awake();
        if (current != mObservedAwake) reconcile();
    }

    private void reconcile() {
        // Main-thread events cancel a settling native worker even if sysfs still says On.
        mGeneration = nativeInvalidate();
        mWorker.removeCallbacksAndMessages(null);
        mObservedAwake = awake();
        if (!mObservedAwake) return;
        final int value;
        try {
            value = Settings.Secure.getIntForUser(getContentResolver(), KEY,
                    ActivityManager.getCurrentUser());
        } catch (Settings.SettingNotFoundException | RuntimeException error) {
            // Unknown is not an implicit ON. A later setting/user/display event retries.
            Log.w(TAG, "Double-tap setting unavailable; keep controller unchanged", error);
            return;
        }
        if (value != 0 && value != 1) return;
        submit(value, mGeneration, 0);
    }

    private void submit(int value, long expectedGeneration, int attempt) {
        mWorker.post(() -> {
            final int result = nativeApply(value, expectedGeneration);
            mMain.post(() -> {
                if (expectedGeneration != mGeneration || !awake()) return;
                if (result == APPLIED) {
                    Log.i(TAG, "mode=14 configured=" + value + "; hardware wake unverified");
                } else if (result != INVALID && attempt < MAX_RETRIES) {
                    // Bounded awake-only retries for firmware resume/provider timing.
                    mMain.postDelayed(() -> {
                        if (expectedGeneration == mGeneration && awake()) {
                            submit(value, expectedGeneration, attempt + 1);
                        }
                    }, 1000);
                } else {
                    Log.w(TAG, "mode=14 deferred/failed result=" + result);
                }
            });
        });
    }
}
