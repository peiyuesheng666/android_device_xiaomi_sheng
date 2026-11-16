// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.app.NotificationManager;
import android.app.ActivityManager;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.res.Configuration;
import android.graphics.PixelFormat;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.UEventObserver;
import android.os.UserHandle;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewTreeObserver;
import android.view.WindowManager;
import android.view.WindowInsets;
import android.view.ViewConfiguration;
import android.view.animation.PathInterpolator;
import android.widget.FrameLayout;
import android.widget.Toast;
import java.util.Objects;
import org.lineageos.sheng.pen.charge.ChargeStatus;

/** Independent read-only charging feedback. It never touches the pen connection actor. */
final class PenChargingMonitor {
    private static final String CHANNEL = "pen_charge";
    private static final int NOTICE = 66;
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Handler worker;
    private final PowerManager power;
    private final BluetoothAdapter bluetooth;
    private final WindowManager windows;
    private ChargeStatus previous = ChargeStatus.unknown();
    private final PenChargeSession session = new PenChargeSession();
    private String cachedName, cachedAddress, displayedName;
    private long nameRefreshAt;
    private FrameLayout window;
    private PenChargeCardView card;
    private final Runnable dismiss = () -> hide(true);
    private final Runnable poll = this::sample;
    private final UEventObserver chargerEvents = new UEventObserver() {
        @Override public void onUEvent(UEvent event) { requestSample(); }
    };
    private final BroadcastReceiver screenChanges = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { requestSample(); }
    };

    PenChargingMonitor(Context context) {
        this.context = context;
        power = context.getSystemService(PowerManager.class);
        windows = context.getSystemService(WindowManager.class);
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        bluetooth = manager == null ? null : manager.getAdapter();
        displayedName = word("手写笔", "Stylus");
        PenPopupVisibility.observe(() -> {
            if (PenPopupVisibility.settingsVisible()) {
                if (session.hasAttachment()) session.dismiss();
                hide(false);
            }
        });
        // Remove feedback left by the earlier installed build. This monitor
        // presents attachment cards only and never posts a notification.
        NotificationManager legacy = context.getSystemService(NotificationManager.class);
        if (legacy != null) { legacy.cancel(NOTICE); legacy.deleteNotificationChannel(CHANNEL); }
        HandlerThread thread = new HandlerThread("ShengPenCharge");
        thread.start(); worker = new Handler(thread.getLooper());
        chargerEvents.startObserving("POWER_SUPPLY_REVERSE_PEN_CHG_STATE=");
        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        context.registerReceiver(screenChanges, filter, Context.RECEIVER_EXPORTED);
        worker.post(poll);
    }

    private String word(String chinese, String english) {
        return context.getResources().getConfiguration().getLocales().get(0).getLanguage().equals("zh")
                ? chinese : english;
    }

    private void requestSample() {
        worker.removeCallbacks(poll);
        worker.post(poll);
    }

    private void sample() {
        worker.removeCallbacks(poll);
        ChargeStatus value = PenChargingState.read();
        String name = readModelName(value);
        main.post(() -> {
            try { publish(value, name); }
            catch (RuntimeException error) { Log.e("ShengPenCharge", "Charging feedback unavailable", error); }
        });
        worker.postDelayed(poll, power.isInteractive() ? 500 : 8000);
    }

    private String readModelName(ChargeStatus status) {
        long now = SystemClock.uptimeMillis();
        if (cachedName != null && Objects.equals(cachedAddress, status.address) && now < nameRefreshAt)
            return cachedName;
        String result = word("手写笔", "Stylus"), single = null;
        int connected = 0;
        try {
            if (bluetooth != null && bluetooth.isEnabled()) {
                for (BluetoothDevice device : bluetooth.getBondedDevices()) {
                    String name = device.getName();
                    if (!"Xiaomi Focus Pen".equals(name) && !"Xiaomi Focus Pen Pro".equals(name)) continue;
                    if (status.address != null && status.address.equals(ChargeStatus.address(device.getAddress()))) {
                        result = name.substring("Xiaomi ".length()); break;
                    }
                    if (status.address == null && device.isConnected()) {
                        connected++; single = name.substring("Xiaomi ".length());
                    }
                }
                if (status.address == null && connected == 1) result = single;
            }
        } catch (RuntimeException unavailable) { /* A missing name cannot affect charging or pen input. */ }
        cachedName = result; cachedAddress = status.address; nameRefreshAt = now + 5000;
        return result;
    }

    private String title(ChargeStatus status) {
        switch (status.state) {
            case ACQUIRING: return word("获取中…", "Getting status…");
            case CHARGING: return word("充电中", "Charging");
            case FULL: return word("已充满", "Fully charged");
            case MISALIGNED: return word("获取失败，请重新吸附", "Couldn't get status. Reattach the pen.");
            case WAITING: return word("已吸附", "Attached");
            case DETACHED:
            case NOT_CHARGING: return word("未充电", "Not charging");
            default: return word("充电状态未知", "Charging status unavailable");
        }
    }

    private void publish(ChargeStatus status, String name) {
        if (status.state != previous.state || status.level != previous.level)
            Log.i("ShengPenCharge", "state=" + status.state + " level=" + status.level);
        previous = status;
        displayedName = name;
        session.update(status);
        if (status.state == ChargeStatus.State.DETACHED) {
            hide(true); return;
        }
        if (!session.hasAttachment()) return;
        if (PenPopupVisibility.settingsVisible()) {
            // The page already presents this attachment; do not replay it on leaving.
            session.dismiss(); hide(false); return;
        }
        if (power.isInteractive()) {
            if (session.shouldShow(status, true)) {
                show(status); session.markShown(status);
            } else if (card != null) render(status);
        } else hide(false);
    }

    private int dp(float value) { return Math.round(value * context.getResources().getDisplayMetrics().density); }

    private void show(ChargeStatus status) {
        main.removeCallbacks(dismiss);
        if (card == null) {
            boolean dark = (context.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                    == Configuration.UI_MODE_NIGHT_YES;
            window = new FrameLayout(context);
            window.setPadding(dp(8), dp(2), dp(8), dp(10));
            window.setClipChildren(false); window.setClipToPadding(false);
            card = new PenChargeCardView(context, dark, this::dismissByUser);
            enableCardActions(card);
            window.addView(card, new FrameLayout.LayoutParams(-1, -2));
            int width = Math.min(dp(240), context.getResources().getDisplayMetrics().widthPixels - dp(16));
            WindowManager.LayoutParams params = new WindowManager.LayoutParams(width,
                    WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.TYPE_SYSTEM_DIALOG,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                            | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
                    PixelFormat.TRANSLUCENT);
            params.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL; params.y = 0;
            // Stay close to the top while respecting the status bar and camera cutout.
            params.setFitInsetsTypes(WindowInsets.Type.statusBars() | WindowInsets.Type.displayCutout());
            params.setTitle("ShengPenCharging");
            final PenChargeCardView entering = card;
            entering.setAlpha(0); entering.setTranslationY(-dp(16));
            entering.setScaleX(.96f); entering.setScaleY(.96f);
            entering.getViewTreeObserver().addOnPreDrawListener(new ViewTreeObserver.OnPreDrawListener() {
                @Override public boolean onPreDraw() {
                    entering.getViewTreeObserver().removeOnPreDrawListener(this);
                    entering.postOnAnimation(() -> {
                        if (card != entering) return;
                        entering.animate().alpha(1).translationY(0).scaleX(1).scaleY(1)
                                .setInterpolator(new PathInterpolator(.16f, 1f, .3f, 1f)).setDuration(420).start();
                    });
                    return true;
                }
            });
            render(status);
            try { windows.addView(window, params); }
            catch (RuntimeException failure) { card = null; window = null; throw failure; }
            Log.i("ShengPenCharge", "card shown: " + status.state);
        }
        render(status);
        main.postDelayed(dismiss, 5500);
    }

    private void render(ChargeStatus status) {
        card.update(displayedName, title(status), status.level,
                status.charging() || status.state == ChargeStatus.State.FULL);
    }

    private void dismissByUser() {
        session.dismiss(); hide(true);
        Log.i("ShengPenCharge", "card dismissed by user");
    }

    private void openSettings() {
        try {
            context.startActivityAsUser(new Intent().setClassName("org.lineageos.sheng.pen",
                    "org.lineageos.sheng.pen.CompatibilityActivity").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    UserHandle.of(ActivityManager.getCurrentUser()));
            session.dismiss();hide(true);
            Log.i("ShengPenCharge","Opened pen settings from charging card");
        } catch (RuntimeException error) {
            Log.w("ShengPenCharge","Pen settings unavailable",error);
            Toast.makeText(context,word("暂时无法打开手写笔设置","Could not open pen settings"),Toast.LENGTH_SHORT).show();
            main.postDelayed(dismiss,5500);
        }
    }

    private void enableCardActions(PenChargeCardView target) {
        float[] down = new float[2];
        PenCardGesture gesture=new PenCardGesture(ViewConfiguration.get(context).getScaledTouchSlop(),dp(40));
        target.setOnClickListener(view->openSettings());
        target.setTooltipText(word("打开手写笔设置","Open pen settings"));
        target.setOnTouchListener((view, event) -> {
            if (view != card) return false;
            float dx = event.getRawX() - down[0], dy = event.getRawY() - down[1];
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    down[0] = event.getRawX(); down[1] = event.getRawY();
                    gesture.down(down[0],down[1]);
                    view.animate().cancel();view.setAlpha(1);view.setScaleX(1);view.setScaleY(1);
                    main.removeCallbacks(dismiss); return true;
                case MotionEvent.ACTION_POINTER_DOWN:
                    gesture.cancel();return true;
                case MotionEvent.ACTION_MOVE:
                    gesture.move(event.getRawX(),event.getRawY());
                    float movement = Math.abs(dy) > Math.abs(dx) ? (dy<0?dy:Math.min(dp(24),dy*.3f)) : 0;
                    view.setTranslationY(movement);
                    view.setAlpha(1 - Math.min(.7f, Math.max(0,-movement) / dp(200)));
                    return true;
                case MotionEvent.ACTION_UP:
                    PenCardGesture.Result result=gesture.up(event.getRawX(),event.getRawY());
                    if(result==PenCardGesture.Result.DISMISS){dismissByUser();return true;}
                    if(result==PenCardGesture.Result.OPEN){view.performClick();return true;}
                    // A horizontal/incomplete drag returns without opening a page.
                case MotionEvent.ACTION_CANCEL:
                    gesture.cancel();
                    view.animate().translationX(0).translationY(0).alpha(1).scaleX(1).scaleY(1)
                            .setInterpolator(new PathInterpolator(.2f, 0f, 0f, 1f)).setDuration(260).start();
                    main.postDelayed(dismiss, 5500); return true;
                default: return true;
            }
        });
    }

    private void hide(boolean animate) {
        main.removeCallbacks(dismiss);
        PenChargeCardView oldCard = card; FrameLayout oldWindow = window;
        card = null; window = null;
        if (oldWindow == null) return;
        oldCard.animate().cancel();
        Runnable remove = () -> {
            try { windows.removeViewImmediate(oldWindow); }
            catch (RuntimeException error) { Log.w("ShengPenCharge", "Charging card already removed", error); }
        };
        if (animate && oldCard.isAttachedToWindow())
            oldCard.animate().alpha(0).translationY(oldCard.getTranslationY() - dp(12)).scaleX(.97f).scaleY(.97f)
                    .setInterpolator(new PathInterpolator(.4f, 0f, .8f, .6f))
                    .setDuration(280).withEndAction(remove).start();
        else remove.run();
    }
}
