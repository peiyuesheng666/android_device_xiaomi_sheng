package com.codex.focuspen;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothProfile;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.input.InputManager;
import android.os.Handler;
import android.os.Binder;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.Log;
import android.view.InputDevice;

import java.io.ByteArrayOutputStream;
import java.io.FileWriter;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.lang.reflect.Field;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Bridge for the Xiaomi Focus Pen on ColorOS 16 pad ports.
 * 现役版本已验证于 muyu(7 Pro) 与 sheng(6S Pro)，对应**非 Pro**的焦点触控笔。
 * PRO 改动点 4/4：换成 Focus Pen Pro 时，除上面的 PEN_MODEL 外还可能需要
 *   · 面板侧笔节点名（Pro 走 P81c profile，见 PRO 指南）
 *   · IPeManager 的广播/Provider 是否对 Pro 有不同 action（需实测）
 */
public final class FocusPenBridge {
    private static final String TAG = "FocusPenBridge";
    private static final String HALL = "/sys/class/qcom-battery/pen_hall3";
    private static final String HALL4 = "/sys/class/qcom-battery/pen_hall4";
    private static final String MAC = "/sys/class/qcom-battery/pen_mac";
    private static final String[] PEN_SOC_NODES = {
            "/sys/class/qcom-battery/reverse_pen_soc",
            "/sys/class/power_supply/battery/reverse_pen_soc"
    };
    private static final String IPE_PACKAGE = "com.oplus.ipemanager";
    private static final String IPE_BONDED = "com.oplus.ipemanager.action.PENCIL_BONDED_WHEN_BOOT";
    private static final String IPE_STATUS = "com.oplus.ipemanager.action.PENCIL_STATUS_CHANGE";
    private static final String IPE_DEVICE_FOUND =
            "com.oplus.ipemanager.ACTION.BROADCAST.OAF_DEVICE_FOUND";
    private static final UUID BATTERY_SERVICE = UUID.fromString("0000180f-0000-1000-8000-00805f9b34fb");
    private static final UUID BATTERY_LEVEL = UUID.fromString("00002a19-0000-1000-8000-00805f9b34fb");
    private static final UUID CLIENT_CONFIG = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private static final String BATTERY_URI =
            "content://com.oplus.ipemanager.provider/integer/local_config/pencil_sp_battery_level/";
    private static final String TOUCH_ENABLE = "/system/penfix/bin/Xiaomipen";
    /** BT name of the pen; the kernel pen_mac node is only populated once the
     *  reverse-wireless-charging link has read the pen, which does not happen on
     *  sheng. Fall back to the bonded/discovered BT entry carrying this name.
     *  PRO 改动点 3/4：这里用 startsWith，所以 "Xiaomi Focus Pen Pro" 天然命中，
     *  通常无需改动；但若要严格区分两种笔（例如分别记录），改成 equals 再各写一条。 */
    private static final String PEN_NAME = "Xiaomi Focus Pen";
    private static final int HID_HOST = 4;
    private static final String HID_STATE_CHANGED =
            "android.bluetooth.input.profile.action.CONNECTION_STATE_CHANGED";
    private static final String PENCIL_ENABLED = "settings_enable_oppo_pencil";
    private static final String PENCIL_STATE = "ipe_pencil_connect_state";
    private static final String BT_ICON_OWNED = "focuspen_bt_icon_managed";

    /* ==== PRO 改动点 1/4 ==================================================
     * Xiaomipen 这个 OEM helper 的调用形式是：  Xiaomipen <pen_model> <pen_enable>
     *   pen_model : 0 = 小米焦点触控笔        （本文件第 245 行现在写死 "0"）
     *               1 = 小米焦点触控笔 Pro
     *   pen_enable: 0 = disable / 1 = enable
     * 用 Pro 笔的话把下面这行改成 "1"。
     * （想两种笔都自动适配，见 PRO 指南"自动判定 pen_model"那一节）
     * ==================================================================== */
    private static final String PEN_MODEL_NON_PRO = "0";
    private static final String PEN_MODEL_PRO     = "1";

    private final Context context;
    private final BluetoothAdapter adapter;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService commands = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "FocusPenCommands");
        thread.setDaemon(true);
        return thread;
    });
    private BluetoothDevice device;
    private BluetoothGatt gatt;
    private BluetoothProfile hidProxy;
    // -1 means unknown: a missing proxy or a failed query is not a disconnect.
    private volatile int confirmedPencilState = -1;
    private boolean pencilFeatureEnabled;
    private long nextHidCheck;
    private long nextHidConnect;
    private long nextIpeRegistration;
    private volatile String connectedHidAddress;
    private boolean hidQueryWarning;
    private boolean settingsWarning;
    private boolean iconWarning;
    private boolean settingsProviderReady;
    private IBinder systemServerBinder;
    private PenInputIdentity.Match hardwarePen;
    private long nextHardwareScan;
    private final IBinder settingsProviderToken = new Binder();
    private InputManager inputManager;
    private long nextTouchCheck;
    private boolean touchWarning;
    private final TouchAwakeGate touchAwakeGate = new TouchAwakeGate();
    private volatile boolean touchCheckQueued;
    private volatile boolean touchInitPending;
    private long touchInitGeneration;
    private final Runnable guardRequest = () -> commands.execute(() ->
            runCommand("Focus Pen report guard", new String[] {
                    "/system/bin/setprop", "sys.focuspen.suppress", "1"}, null));
    private volatile String address;
    private int stableHall = -1;
    private int pendingHall = -1;
    private int pendingCount;
    private int lastBattery = -1;
    private String lastBatteryAddress;
    private long nextBatteryAttempt;
    private int lastBondState = BluetoothDevice.BOND_NONE;
    private long nextBondAttempt;
    private long nextGattAttempt;
    private long gattDeadline;
    private long hidRequestAt;
    private boolean gattConnected;
    private volatile boolean attached;
    private boolean hidRequested;
    private static boolean hallReadWarned;
    private int probeTick;
    private volatile BluetoothDevice discoveredPen;
    private long nextDiscovery;

    private FocusPenBridge(Context context, BluetoothAdapter adapter) {
        this.context = context;
        this.adapter = adapter;
    }

    public static void main(String[] args) throws Exception {
        String contextLabel = readNode("/proc/self/attr/current");
        if (!"u:r:system_app:s0".equals(contextLabel)) {
            throw new SecurityException("Unexpected Focus Pen service context: " + contextLabel);
        }
        Log.i(TAG, "unified C16/C17 v1.1.0 started in " + contextLabel);
        Looper.prepareMainLooper();
        Context context = (Context) Class.forName("android.app.ActivityThread")
                .getMethod("getSystemContext")
                .invoke(Class.forName("android.app.ActivityThread")
                        .getMethod("systemMain").invoke(null));
        // Standalone app_process does not always initialize the Bluetooth framework manager.
        try {
            Class<?> manager = Class.forName("android.os.BluetoothServiceManager");
            java.lang.reflect.Constructor<?> constructor = manager.getDeclaredConstructor();
            constructor.setAccessible(true);
            Object instance = constructor.newInstance();
            Class.forName("android.bluetooth.BluetoothFrameworkInitializer")
                    .getMethod("setBluetoothServiceManager", manager).invoke(null, instance);
        } catch (Throwable e) {
            Log.w(TAG, "Bluetooth manager setup: " + e);
        }
        BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
        if (adapter == null) {
            try {
                Method createAdapter = BluetoothAdapter.class.getDeclaredMethod("createAdapter", Context.class);
                createAdapter.setAccessible(true);
                adapter = (BluetoothAdapter) createAdapter.invoke(null, context);
            } catch (Throwable e) {
                Log.e(TAG, "Bluetooth adapter setup failed", e);
            }
        }
        if (adapter == null) throw new IllegalStateException("Bluetooth adapter unavailable");
        FocusPenBridge bridge = new FocusPenBridge(context, adapter);
        bridge.watchSystemServer();
        Log.i(TAG, "started; waiting for real Focus Pen hall and MAC nodes");
        bridge.watchNoisyInput();
        bridge.watchPenDiscovery();
        bridge.watchHidState();
        bridge.ensureHid();
        bridge.enableTouch("boot");
        bridge.handler.post(bridge::tick);
        // The original successful bridge registered again after Oplus boot cleanup.
        bridge.handler.postDelayed(() -> {
            if (bridge.attached && bridge.device != null
                    && bridge.device.getBondState() == BluetoothDevice.BOND_BONDED) {
                bridge.registerBonded();
            }
        }, 240000);
        Looper.loop();
    }

    private static String readNode(String path) {
        return TouchNodeReader.read(path);
    }

    private void watchSystemServer() {
        if (systemServerBinder != null) return;
        try {
            IBinder service = (IBinder) Class.forName("android.os.ServiceManager")
                    .getMethod("getService", String.class).invoke(null, "activity");
            if (service == null) return;
            service.linkToDeath(() -> {
                // init owns this process, so a framework restart does not kill it.
                // Exit on AMS death: init restarts us with fresh Context, Bluetooth
                // manager, profile, receivers and Settings provider Binder handles.
                Log.w(TAG, "System server died; exiting for init to rebuild service handles");
                android.os.Process.killProcess(android.os.Process.myPid());
            }, 0);
            systemServerBinder = service;
            Log.i(TAG, "System-server death recovery armed");
        } catch (Throwable e) {
            Log.w(TAG, "System-server watcher unavailable; retrying on next poll", e);
        }
    }

    private boolean touchAwake() {
        try {
            PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            String dpms = readNode("/sys/class/drm/card0-DSI-1/dpms");
            return touchAwakeGate.ready(power != null && power.isInteractive(), dpms,
                    android.os.SystemClock.elapsedRealtime());
        } catch (Throwable e) {
            touchAwakeGate.ready(false, "", android.os.SystemClock.elapsedRealtime());
            return false;
        }
    }

    private static String normalizeMac(String raw) {
        return PenInputIdentity.normalizeMac(raw);
    }

    private PenInputIdentity.Match hardwarePen() {
        long now = android.os.SystemClock.elapsedRealtime();
        if (now >= nextHardwareScan) {
            nextHardwareScan = now + 5000;
            hardwarePen = PenInputIdentity.find("/sys/class/input");
        }
        return hardwarePen;
    }

    private void tick() {
        try {
            watchSystemServer();
            boolean touchReady = touchAwake();
            if (touchReady && android.os.SystemClock.elapsedRealtime() >= nextTouchCheck) {
                nextTouchCheck = android.os.SystemClock.elapsedRealtime() + 5000;
                ensureTouchEnabled();
            }
            if (android.os.SystemClock.elapsedRealtime() >= nextHidCheck) {
                nextHidCheck = android.os.SystemClock.elapsedRealtime() + 5000;
                ensureHid();
                refreshHidState("poll");
                if (!attached) refreshConnectedBattery();
            }
            String rawHall3 = readNode(HALL);
            String rawHall4 = readNode(HALL4);
            String rawMac = readNode(MAC);
            if ((rawHall3 == null && rawHall4 == null) && !hallReadWarned) {
                hallReadWarned = true;
                Log.e(TAG, "Cannot read Focus Pen magnetic sensor hall3=" + rawHall3 + " hall4=" + rawHall4);
            }
            int hall3 = parseHall(rawHall3);
            int hall4 = parseHall(rawHall4);
            // sheng has two pen hall nodes (pen_hall3 / pen_hall4); either reading 0
            // means magnetic attachment (same driver family / convention as muyu).
            int combined = (hall3 == 0 || hall4 == 0) ? 0
                    : ((hall3 == 1 || hall4 == 1) ? 1 : -1);
            if ((++probeTick % 10) == 0) {
                Log.i(TAG, "probe hall3=" + rawHall3 + " hall4=" + rawHall4
                        + " mac=" + rawMac + " combined=" + combined + " attached=" + attached
                        + " bonded=[" + bondedSummary() + "]");
            }
            int hall = combined;
            if (hall == 0 || hall == 1) {
                if (hall != stableHall) {
                    if (hall != pendingHall) { pendingHall = hall; pendingCount = 1; }
                    else if (++pendingCount >= 2) {
                        stableHall = hall;
                        pendingCount = 0;
                        if (hall == 0) attach(); else detach();
                    }
                } else {
                    pendingCount = 0;
                }
            }
            if (attached) advance();
        } catch (Throwable e) {
            Log.e(TAG, "poll failure", e);
        } finally {
            handler.postDelayed(this::tick, 500);
        }
    }

    private static int parseHall(String raw) {
        if (raw == null) return -1;
        try {
            return Integer.parseInt(raw.trim());
        } catch (Throwable e) {
            return -1;
        }
    }

    private String bondedSummary() {
        try {
            StringBuilder sb = new StringBuilder();
            for (BluetoothDevice d : adapter.getBondedDevices()) {
                if (sb.length() > 0) sb.append(';');
                sb.append(d.getName()).append('@').append(d.getAddress());
            }
            return sb.length() == 0 ? "none" : sb.toString();
        } catch (Throwable e) {
            return "err:" + e;
        }
    }

    private void attach() {
        attached = true;
        Log.i(TAG, "magnetic attachment detected");
        enableTouch("attach");
        advance();
    }

    private void enableTouch(String trigger) {
        synchronized (this) { touchInitPending = true; touchInitGeneration++; }
        nextTouchCheck = 0;
        requestGuard();
        ensureTouchEnabled();
    }

    private void ensureTouchEnabled() {
        if (!touchAwake() || touchCheckQueued) return;
        touchCheckQueued = true;
        commands.execute(() -> {
            try { configureAwakeTouch(); }
            finally { touchCheckQueued = false; }
        });
    }

    private void configureAwakeTouch() {
        if (!touchAwake()) return;
        String path = "/proc/xm_htc_stylus_enable";
        try {
            int state = TouchNodeReader.stylusState(readNode(path));
            if (state < 0) throw new IllegalStateException("stylus state unavailable; no write");
            if (state == 0) {
                if (!touchAwake()) return;
                try (FileWriter writer = new FileWriter(path)) { writer.write("1\n"); }
                state = TouchNodeReader.stylusState(readNode(path));
                if (state != 1)
                    throw new IllegalStateException("readback=" + state);
                Log.i(TAG, "pen tip enabled and verified");
            }
            if (touchInitPending && touchAwake()) {
                final long generation;
                synchronized (this) { generation = touchInitGeneration; }
                String model = resolvePenModel();
                if (!touchAwake()) return;
                boolean completed = runCommand("Focus Pen deferred touch enable",
                        new String[] {TOUCH_ENABLE, model, "1"}, null);
                synchronized (this) {
                    if (completed && generation == touchInitGeneration) touchInitPending = false;
                }
                Log.i(TAG, "awake touch init model=" + model + " completed=" + completed);
            }
            touchWarning = false;
        } catch (Throwable e) {
            if (!touchWarning) Log.e(TAG, "pen tip enable failed", e);
            touchWarning = true;
        }
    }

    private void requestGuard() {
        handler.removeCallbacks(guardRequest);
        handler.postDelayed(guardRequest, 250);
    }

    private void watchNoisyInput() {
        inputManager = (InputManager) context.getSystemService(Context.INPUT_SERVICE);
        if (inputManager == null) {
            Log.e(TAG, "InputManager unavailable; noisy Focus Pen report cannot be suppressed");
            return;
        }
        inputManager.registerInputDeviceListener(new InputManager.InputDeviceListener() {
            @Override public void onInputDeviceAdded(int id) { suppressNoisyInput(id); requestHidStateCheck(); }
            @Override public void onInputDeviceRemoved(int id) { requestHidStateCheck(); }
            @Override public void onInputDeviceChanged(int id) { suppressNoisyInput(id); requestHidStateCheck(); }
        }, handler);
        for (int id : inputManager.getInputDeviceIds()) suppressNoisyInput(id);
    }

    private final Runnable hidStateCheck = () -> {
        ensureHid();
        refreshHidState("input devices changed");
    };

    private void requestHidStateCheck() {
        // InputManager callbacks work in standalone app_process even when this
        // ROM ignores an unregistered process's Bluetooth broadcast receiver.
        nextHardwareScan = 0;
        handler.removeCallbacks(hidStateCheck);
        handler.postDelayed(hidStateCheck, 250);
    }

    private void suppressNoisyInput(int id) {
        if (inputManager == null) return;
        InputDevice input = inputManager.getInputDevice(id);
        if (input == null || input.getVendorId() != 0x0022) return;
        int product = input.getProductId();
        if (product != 0x4d80 && product != 0x5081) return;   /* 非 Pro + Pro */
        // Android merges mouse, buttons and reports into one logical device.
        // The one-shot helper selects only the exact raw report subdevice.
        requestGuard();
    }

    private void detach() {
        if (!attached) return;
        attached = false;
        Log.i(TAG, "magnetic detachment detected");
        ensureTouchEnabled();
        if (address != null) announce(false);
        closeGatt();
        // Keep the HID observer alive when the pen is taken off the charger.
        // Magnetic detachment and battery GATT cleanup do not mean HID disconnected.
        device = null;
        address = null;
        lastBattery = -1;
        nextBatteryAttempt = 0;
        nextBondAttempt = 0;
        nextGattAttempt = 0;
        lastBondState = BluetoothDevice.BOND_NONE;
    }

    private void advance() {
        String now = resolvePenAddress();
        if (now == null) {
            // Kernel pen_mac not ready (reverse-wireless-charging link absent on
            // sheng): try to locate the pen through Bluetooth instead.
            maybeDiscover();
            return; // Never pair an unrelated BLE device or a remembered MAC.
        }
        if (!now.equals(address)) {
            if (address != null) { announce(false); closeGatt(); }
            address = now;
            device = adapter.getRemoteDevice(now);
            lastBattery = -1;
            nextBatteryAttempt = 0;
            nextBondAttempt = 0;
            nextGattAttempt = 0;
            lastBondState = BluetoothDevice.BOND_NONE;
            Log.i(TAG, "Focus Pen address obtained from kernel");
        }
        if (!adapter.isEnabled() || device == null) return;
        refreshBattery();
        int bond = device.getBondState();
        if (bond == BluetoothDevice.BOND_NONE && android.os.SystemClock.elapsedRealtime() >= nextBondAttempt) {
            nextBondAttempt = android.os.SystemClock.elapsedRealtime() + 6000;
            try {
                // Older Android builds expose LE transport pairing only as a hidden method.
                Method method = BluetoothDevice.class.getMethod("createBond", int.class);
                Log.i(TAG, "createBond(LE)=" + method.invoke(device, BluetoothDevice.TRANSPORT_LE));
            } catch (Throwable e) {
                Log.i(TAG, "createBond()=" + device.createBond());
            }
        }
        if (bond != BluetoothDevice.BOND_BONDED) {
            lastBondState = bond;
            return;
        }
        if (lastBondState != BluetoothDevice.BOND_BONDED) {
            lastBondState = bond;
            registerBonded();
        }
        ensureHid();
        if (gatt != null && !gattConnected && android.os.SystemClock.elapsedRealtime() > gattDeadline) {
            Log.w(TAG, "GATT connection timed out");
            closeGatt();
            nextGattAttempt = android.os.SystemClock.elapsedRealtime() + 3000;
        }
        if (gatt == null && android.os.SystemClock.elapsedRealtime() >= nextGattAttempt) {
            nextGattAttempt = android.os.SystemClock.elapsedRealtime() + 3000;
            try {
                gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE);
                gattDeadline = android.os.SystemClock.elapsedRealtime() + 10000;
                Log.i(TAG, "GATT connection requested=" + (gatt != null));
            } catch (Throwable e) {
                Log.e(TAG, "GATT connection request failed", e);
            }
        }
    }

    /** Kernel pen_mac first (authoritative when reverse charging is up); otherwise
     *  fall back to a bonded or freshly-discovered BT entry named "Xiaomi Focus Pen". */
    private String resolvePenAddress() {
        String kernel = normalizeMac(readNode(MAC));
        if (kernel != null) return kernel;
        PenInputIdentity.Match hardware = hardwarePen();
        if (hardware != null) return hardware.address;
        try {
            for (BluetoothDevice bonded : adapter.getBondedDevices()) {
                String name = bonded.getName();
                if (name != null && name.startsWith(PEN_NAME)) return bonded.getAddress();
            }
        } catch (Throwable e) {
            Log.w(TAG, "bonded device scan failed: " + e);
        }
        BluetoothDevice found = discoveredPen;
        return found == null ? null : found.getAddress();
    }

    /** 按当前解析到的笔名决定 Xiaomipen 的 pen_model：Pro=1，否则=0。 */
    private String resolvePenModel() {
        PenInputIdentity.Match hardware = hardwarePen();
        if (hardware != null && "5081".equals(hardware.product)) return PEN_MODEL_PRO;
        String addr = resolvePenAddress();
        if (addr != null) {
            try {
                String remoteName = adapter.getRemoteDevice(addr).getName();
                if (remoteName != null && remoteName.startsWith("Xiaomi Focus Pen Pro")) return PEN_MODEL_PRO;
                for (BluetoothDevice bonded : adapter.getBondedDevices()) {
                    if (addr.equalsIgnoreCase(bonded.getAddress())) {
                        String n = bonded.getName();
                        return (n != null && n.startsWith("Xiaomi Focus Pen Pro"))
                                ? PEN_MODEL_PRO : PEN_MODEL_NON_PRO;
                    }
                }
            } catch (Throwable ignored) { }
        }
        BluetoothDevice found = discoveredPen;
        if (found != null) {
            String n = found.getName();
            if (n != null && n.startsWith("Xiaomi Focus Pen Pro")) return PEN_MODEL_PRO;
        }
        return PEN_MODEL_NON_PRO;
    }

    private void watchPenDiscovery() {
        try {
            context.registerReceiver(new BroadcastReceiver() {
                @Override public void onReceive(Context ctx, Intent intent) {
                    BluetoothDevice device = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE);
                    if (device == null) return;
                    String name = device.getName();
                    if (name != null && name.startsWith(PEN_NAME)) {
                        discoveredPen = device;
                        Log.i(TAG, "discovered pen name=" + name + " addr=" + device.getAddress());
                    }
                }
            }, new IntentFilter(BluetoothDevice.ACTION_FOUND));
            Log.i(TAG, "pen discovery receiver registered");
        } catch (Throwable e) {
            Log.w(TAG, "pen discovery receiver failed: " + e);
        }
    }

    private void maybeDiscover() {
        if (discoveredPen != null || !attached) return;
        if (android.os.SystemClock.elapsedRealtime() < nextDiscovery) return;
        nextDiscovery = android.os.SystemClock.elapsedRealtime() + 20000;
        try {
            if (adapter.isDiscovering()) adapter.cancelDiscovery();
            boolean started = adapter.startDiscovery();
            Log.i(TAG, "startDiscovery=" + started);
        } catch (Throwable e) {
            Log.w(TAG, "startDiscovery failed: " + e);
        }
    }

    private void announce(boolean present) {
        announceAction(IPE_STATUS, present);
    }

    private void registerBonded() {
        if (address == null || !attached) return;
        String registeredAddress = address;
        announceAction(IPE_BONDED, true);
        handler.postDelayed(() -> {
            if (attached && registeredAddress.equals(address)) announce(true);
        }, 5000);
    }

    private void announceAction(String action, boolean present) {
        if (address == null) return;
        // A standalone app_process has no AMS application record. Use the same
        // shell-command Binder path as the previously working system-UID bridge.
        String mac = address.replace(":", "");
        commands.execute(() -> {
            boolean delivered = runCommand("IPE " + action,
                    new String[] {"/system/bin/cmd", "activity", "start-service",
                            "-n", IPE_PACKAGE + "/.btadsorb.CoreService", "-a", action,
                            "--es", "present", present ? "1" : "0",
                            "--es", "macAddr", mac}, null);
            Log.i(TAG, "IPE " + action + " present=" + present + " delivered=" + delivered);
        });
    }

    private boolean isFocusPen(BluetoothDevice candidate) {
        if (candidate == null) return false;
        String name = candidate.getName();
        if (name != null && name.startsWith(PEN_NAME)) return true;
        String mac = candidate.getAddress();
        PenInputIdentity.Match hardware = hardwarePen();
        return mac.equalsIgnoreCase(address)
                || (hardware != null && mac.equalsIgnoreCase(hardware.address))
                || mac.equalsIgnoreCase(normalizeMac(readNode(MAC)))
                || (discoveredPen != null && mac.equalsIgnoreCase(discoveredPen.getAddress()));
    }

    private void watchHidState() {
        IntentFilter filter = new IntentFilter(HID_STATE_CHANGED);
        filter.addAction(BluetoothAdapter.ACTION_STATE_CHANGED);
        BroadcastReceiver receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context ctx, Intent intent) {
                if (BluetoothAdapter.ACTION_STATE_CHANGED.equals(intent.getAction())) {
                    int state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
                    Log.i(TAG, "Bluetooth state broadcast=" + state);
                    if (state == BluetoothAdapter.STATE_OFF || state == BluetoothAdapter.STATE_TURNING_OFF) {
                        closeHid();
                        setPencilState(false, "bluetooth off");
                    } else if (state == BluetoothAdapter.STATE_ON) {
                        ensureHid();
                        refreshHidState("bluetooth on");
                    }
                    return;
                }
                BluetoothDevice changed = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE);
                if (!isFocusPen(changed)) return;
                int state = intent.getIntExtra(BluetoothProfile.EXTRA_STATE, -1);
                Log.i(TAG, "Focus Pen HID broadcast=" + state);
                if (state == BluetoothProfile.STATE_CONNECTED) {
                    setPencilState(true, "HID connected");
                    registerIpeHid(changed);
                } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
                    // Query the complete profile so a second connected Focus Pen is preserved.
                    // If the proxy is temporarily absent, defer until an authoritative query.
                    refreshHidState("HID disconnected");
                }
            }
        };
        try {
            // A normal Context registration is silently ignored for this
            // unregistered app_process on this ROM. Use a caller-less receiver,
            // which AMS delivers directly through its IIntentReceiver Binder.
            Field packageField = context.getClass().getDeclaredField("mPackageInfo");
            packageField.setAccessible(true);
            Object loadedPackage = packageField.get(context);
            Object dispatcher = loadedPackage.getClass().getMethod("getReceiverDispatcher",
                    BroadcastReceiver.class, Context.class, Handler.class,
                    Class.forName("android.app.Instrumentation"), boolean.class)
                    .invoke(loadedPackage, receiver, context, handler, null, true);
            Object manager = Class.forName("android.app.ActivityManager").getMethod("getService").invoke(null);
            Class.forName("android.app.IActivityManager").getMethod("registerReceiverWithFeature",
                    Class.forName("android.app.IApplicationThread"), String.class, String.class,
                    String.class, Class.forName("android.content.IIntentReceiver"), IntentFilter.class,
                    String.class, int.class, int.class)
                    .invoke(manager, null, "android", null, TAG, dispatcher, filter, null, 0,
                            Context.RECEIVER_EXPORTED);
            Log.i(TAG, "Standalone HID receiver registered");
        } catch (Throwable e) {
            Log.w(TAG, "HID receiver unavailable; using five-second profile queries", e);
        }
    }

    private void refreshHidState(String reason) {
        try {
            if (!adapter.isEnabled()) {
                setPencilState(false, "bluetooth off");
                return;
            }
            if (hidProxy == null) {
                restorePencilSettings();
                return;
            }
            BluetoothDevice connected = null;
            for (BluetoothDevice candidate : hidProxy.getConnectedDevices()) {
                if (isFocusPen(candidate)) { connected = candidate; break; }
            }
            hidQueryWarning = false;
            setPencilState(connected != null, reason);
            if (connected != null) registerIpeHid(connected);
        } catch (Throwable e) {
            if (!hidQueryWarning) Log.w(TAG, "HID state query failed; retaining last state", e);
            hidQueryWarning = true;
        }
    }

    private void setPencilState(boolean connected, String reason) {
        int state = connected ? 2 : 0;
        if (connected) pencilFeatureEnabled = true;
        else {
            connectedHidAddress = null;
            nextIpeRegistration = 0;
        }
        if (state != confirmedPencilState) {
            confirmedPencilState = state;
            Log.i(TAG, "pencil HID state=" + state + " reason=" + reason);
            if (connected) enableTouch("HID connected");
        }
        restorePencilSettings();
    }

    private void registerIpeHid(BluetoothDevice pen) {
        final String mac = pen.getAddress();
        long now = android.os.SystemClock.elapsedRealtime();
        if (mac.equalsIgnoreCase(connectedHidAddress) && now < nextIpeRegistration) return;
        connectedHidAddress = mac;
        nextIpeRegistration = now + 30000;
        // Global settings drive the display, but the settings page reads an
        // IUIPageCallback owned by IPeManager's own GATT connection. The boot
        // action rejects Xiaomi's name. Its external-device discovery action
        // accepts the real paired MAC and lets IPeManager establish that link.
        // Repeating this idempotent action also recovers an IPeManager restart.
        commands.execute(() -> {
            if (!mac.equalsIgnoreCase(connectedHidAddress) || !adapter.isEnabled()) return;
            boolean delivered = runCommand("IPE Focus Pen HID registration",
                    new String[] {"/system/bin/cmd", "activity", "start-service", "--user", "0", "-f", "0x20", "-n",
                            IPE_PACKAGE + "/.btadsorb.CoreService", "-a", IPE_DEVICE_FOUND,
                            "--es", "macAddr", mac, "--es", "deviceType", "pen"}, null);
            Log.i(TAG, "IPE HID registration delivered=" + delivered);
        });
    }

    private void restorePencilSettings() {
        if (confirmedPencilState < 0) return;
        try {
            prepareSettingsProvider();
            // Once enabled, keep the feature on even after a real disconnect.
            if (pencilFeatureEnabled) putGlobalIfChanged(PENCIL_ENABLED, 1);
            putGlobalIfChanged(PENCIL_STATE, confirmedPencilState);
            updateBluetoothIcon();
            settingsWarning = false;
        } catch (Throwable e) {
            if (!settingsWarning) Log.e(TAG, "Pencil settings sync failed; will retry", e);
            settingsWarning = true;
        }
    }

    private void prepareSettingsProvider() throws Exception {
        if (settingsProviderReady) return;
        // init's app_process is not registered as an AMS application. Acquire
        // an external provider reference, then let Settings.Global perform its
        // normal Binder calls with the system context's "android" attribution.
        Object activityManager = Class.forName("android.app.ActivityManager")
                .getMethod("getService").invoke(null);
        Object holder = Class.forName("android.app.IActivityManager")
                .getMethod("getContentProviderExternal", String.class, int.class, IBinder.class, String.class)
                .invoke(activityManager, "settings", 0, settingsProviderToken, TAG);
        if (holder == null) throw new IllegalStateException("Settings provider unavailable");
        Object provider = holder.getClass().getField("provider").get(holder);
        if (provider == null) throw new IllegalStateException("Settings provider Binder unavailable");
        for (Class<?> table : new Class<?>[] {Settings.Global.class, Settings.Secure.class}) {
            Field holderField = table.getDeclaredField("sProviderHolder");
            holderField.setAccessible(true);
            Object settingsHolder = holderField.get(null);
            Field providerField = settingsHolder.getClass().getDeclaredField("mContentProvider");
            providerField.setAccessible(true);
            providerField.set(settingsHolder, provider);
        }
        settingsProviderReady = true;
        if (Settings.Global.getInt(context.getContentResolver(), PENCIL_ENABLED, 0) == 1) {
            pencilFeatureEnabled = true;
        }
        Log.i(TAG, "Settings.Global external provider ready");
    }

    private void putGlobalIfChanged(String key, int value) {
        if (Settings.Global.getInt(context.getContentResolver(), key, -1) == value) return;
        if (!Settings.Global.putInt(context.getContentResolver(), key, value)) {
            throw new IllegalStateException("Failed to write " + key);
        }
        Log.i(TAG, "global " + key + "=" + value);
    }

    private void updateBluetoothIcon() {
        try {
            boolean otherConnected = false;
            if (confirmedPencilState == 2) {
                Method isConnected = BluetoothDevice.class.getMethod("isConnected");
                for (BluetoothDevice candidate : adapter.getBondedDevices()) {
                    if (!isFocusPen(candidate) && Boolean.TRUE.equals(isConnected.invoke(candidate))) {
                        otherConnected = true;
                        break;
                    }
                }
            }
            boolean hide = confirmedPencilState == 2 && !otherConnected;
            String original = Settings.Secure.getString(context.getContentResolver(), "icon_blacklist");
            boolean contains = false;
            StringBuilder withoutBluetooth = new StringBuilder();
            if (original != null && !original.isEmpty()) {
                for (String slot : original.split(",")) {
                    if ("bluetooth".equals(slot.trim())) { contains = true; continue; }
                    if (withoutBluetooth.length() > 0) withoutBluetooth.append(',');
                    withoutBluetooth.append(slot);
                }
            }
            boolean owned = Settings.Global.getInt(context.getContentResolver(), BT_ICON_OWNED, 0) == 1;
            if (hide && !contains) {
                putGlobalIfChanged(BT_ICON_OWNED, 1);
                String next = withoutBluetooth.length() == 0 ? "bluetooth" : withoutBluetooth + ",bluetooth";
                if (!Settings.Secure.putString(context.getContentResolver(), "icon_blacklist", next)) {
                    throw new IllegalStateException("Bluetooth icon hide failed");
                }
                Log.i(TAG, "Bluetooth status icon hidden for Focus Pen only");
            } else if (!hide && owned) {
                if (contains && !Settings.Secure.putString(context.getContentResolver(),
                        "icon_blacklist", withoutBluetooth.toString())) {
                    throw new IllegalStateException("Bluetooth icon restore failed");
                }
                putGlobalIfChanged(BT_ICON_OWNED, 0);
                Log.i(TAG, "Bluetooth status icon restored");
            }
            iconWarning = false;
        } catch (Throwable e) {
            if (!iconWarning) Log.w(TAG, "Focus Pen Bluetooth icon policy failed", e);
            iconWarning = true;
        }
    }

    private void ensureHid() {
        if (!adapter.isEnabled()) return;
        if (hidRequested && hidProxy == null && android.os.SystemClock.elapsedRealtime() - hidRequestAt > 10000) {
            hidRequested = false;
        }
        if (hidProxy != null) { connectHidIfAttached(); return; }
        if (hidRequested) return;
        try {
            hidRequestAt = android.os.SystemClock.elapsedRealtime();
            hidRequested = adapter.getProfileProxy(context, new BluetoothProfile.ServiceListener() {
                @Override public void onServiceConnected(int profile, BluetoothProfile proxy) {
                    handler.post(() -> {
                        if (profile != HID_HOST) return;
                        hidProxy = proxy;
                        refreshHidState("HID proxy ready");
                        connectHidIfAttached();
                    });
                }
                @Override public void onServiceDisconnected(int profile) {
                    handler.post(() -> { hidProxy = null; hidRequested = false; });
                }
            }, HID_HOST);
        } catch (Throwable e) {
            hidRequested = false;
            Log.w(TAG, "HID proxy unavailable: " + e);
        }
    }

    private void connectHidIfAttached() {
        if (!attached || device == null || device.getBondState() != BluetoothDevice.BOND_BONDED
                || android.os.SystemClock.elapsedRealtime() < nextHidConnect) return;
        nextHidConnect = android.os.SystemClock.elapsedRealtime() + 6000;
        try {
            if (hidProxy.getConnectionState(device) != BluetoothProfile.STATE_DISCONNECTED) return;
            Method policy = hidProxy.getClass().getMethod("setConnectionPolicy", BluetoothDevice.class, int.class);
            policy.invoke(hidProxy, device, 100);
            Method connect = hidProxy.getClass().getMethod("connect", BluetoothDevice.class);
            Log.i(TAG, "HID connect=" + connect.invoke(hidProxy, device));
        } catch (Throwable e) {
            Log.w(TAG, "HID explicit connect unavailable: " + e);
        }
    }

    private void closeHid() {
        if (hidProxy != null) {
            try { adapter.closeProfileProxy(HID_HOST, hidProxy); } catch (Throwable ignored) { }
        }
        hidProxy = null;
        hidRequested = false;
    }

    private void closeGatt() {
        BluetoothGatt old = gatt;
        gatt = null;
        gattConnected = false;
        if (old != null) {
            try { old.disconnect(); } catch (Throwable ignored) { }
            try { old.close(); } catch (Throwable ignored) { }
        }
    }

    private void refreshBattery() {
        for (String path : PEN_SOC_NODES) {
            String raw = readNode(path);
            if (raw == null) continue;
            try {
                int level = Integer.parseInt(raw);
                if (level >= 0 && level <= 100) { battery(new byte[] {(byte) level}); return; }
            } catch (NumberFormatException ignored) { }
        }
        try {
            Method method = BluetoothDevice.class.getMethod("getBatteryLevel");
            int level = (Integer) method.invoke(device);
            if (level >= 0 && level <= 100) battery(new byte[] {(byte) level});
        } catch (Throwable ignored) { }
    }

    private void battery(byte[] data) {
        if (data == null || data.length == 0 || !attached) return;
        publishBattery(address, data[0] & 0xff);
    }

    private boolean currentBatterySource(String mac) {
        return mac != null && ((attached && mac.equalsIgnoreCase(address))
                || (confirmedPencilState == 2 && mac.equalsIgnoreCase(connectedHidAddress)));
    }

    private void refreshConnectedBattery() {
        String mac = connectedHidAddress;
        if (confirmedPencilState != 2 || mac == null) return;
        try {
            int level = (Integer) BluetoothDevice.class.getMethod("getBatteryLevel")
                    .invoke(adapter.getRemoteDevice(mac));
            publishBattery(mac, level);
        } catch (Throwable ignored) { }
    }

    private void publishBattery(String sourceAddress, int level) {
        if (!currentBatterySource(sourceAddress) || level < 0 || level > 100) return;
        if (!sourceAddress.equalsIgnoreCase(lastBatteryAddress)) {
            lastBattery = -1;
            nextBatteryAttempt = 0;
        }
        if (level == lastBattery) return;
        if (android.os.SystemClock.elapsedRealtime() < nextBatteryAttempt) return;
        nextBatteryAttempt = android.os.SystemClock.elapsedRealtime() + 15000;
        String expectedAddress = sourceAddress;
        commands.execute(() -> {
            if (!currentBatterySource(expectedAddress)) return;
            boolean written = runCommand("IPE battery",
                    new String[] {"/system/bin/app_process", "/system/bin",
                            "com.android.commands.content.Content", "insert", "--uri",
                            BATTERY_URI + level, "--bind", "pencil_sp_battery_level:i:" + level,
                            "--bind", "focuspen_mac:s:" + expectedAddress},
                    "/system/framework/content.jar");
            if (written) handler.post(() -> {
                if (currentBatterySource(expectedAddress)) {
                    lastBattery = level;
                    lastBatteryAddress = expectedAddress;
                    Log.i(TAG, "battery updated=" + level);
                }
            });
        });
    }

    private static boolean runCommand(String operation, String[] argv, String classPath) {
        Process process = null;
        try {
            ProcessBuilder builder = new ProcessBuilder(argv).redirectErrorStream(true);
            if (classPath != null) builder.environment().put("CLASSPATH", classPath);
            process = builder.start();
            if (!process.waitFor(10, TimeUnit.SECONDS)) {
                process.destroyForcibly();
                Log.e(TAG, operation + " timed out");
                return false;
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream stream = process.getInputStream()) {
                byte[] buffer = new byte[512];
                int count;
                while ((count = stream.read(buffer)) != -1 && output.size() < 2048) {
                    output.write(buffer, 0, Math.min(count, 2048 - output.size()));
                }
            }
            String result = output.toString("UTF-8");
            // The Android content command can report a provider exception on
            // stderr while still returning exit code zero.
            if (process.exitValue() == 0 && !result.contains("Error while accessing provider")
                    && !result.contains("Exception") && !result.contains("Permission denied")) {
                return true;
            }
            Log.e(TAG, operation + " failed rc=" + process.exitValue() + " output=" + result);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (process != null) process.destroyForcibly();
            Log.e(TAG, operation + " interrupted", e);
        } catch (Throwable e) {
            if (process != null) process.destroyForcibly();
            Log.e(TAG, operation + " failed", e);
        }
        return false;
    }

    private final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt connection, int status, int state) {
            handler.post(() -> {
                if (connection != gatt) return;
                if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED) {
                    gattConnected = true;
                    connection.discoverServices();
                    Log.i(TAG, "GATT connected");
                } else if (state == BluetoothProfile.STATE_DISCONNECTED || status != BluetoothGatt.GATT_SUCCESS) {
                    Log.w(TAG, "GATT disconnected status=" + status);
                    closeGatt();
                    nextGattAttempt = android.os.SystemClock.elapsedRealtime() + 3000;
                }
            });
        }
        @Override public void onServicesDiscovered(BluetoothGatt connection, int status) {
            if (connection != gatt || status != BluetoothGatt.GATT_SUCCESS) return;
            BluetoothGattService service = connection.getService(BATTERY_SERVICE);
            BluetoothGattCharacteristic characteristic = service == null ? null : service.getCharacteristic(BATTERY_LEVEL);
            if (characteristic == null) { Log.w(TAG, "battery characteristic unavailable"); return; }
            connection.readCharacteristic(characteristic);
        }
        @Override public void onCharacteristicRead(BluetoothGatt connection, BluetoothGattCharacteristic characteristic, int status) {
            if (connection != gatt || !BATTERY_LEVEL.equals(characteristic.getUuid())) return;
            if (status == BluetoothGatt.GATT_SUCCESS) {
                byte[] value = characteristic.getValue();
                handler.post(() -> battery(value));
            }
            BluetoothGattDescriptor descriptor = characteristic.getDescriptor(CLIENT_CONFIG);
            if (descriptor != null && connection.setCharacteristicNotification(characteristic, true)) {
                descriptor.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                connection.writeDescriptor(descriptor);
            }
        }
        @Override public void onCharacteristicChanged(BluetoothGatt connection, BluetoothGattCharacteristic characteristic) {
            if (connection == gatt && BATTERY_LEVEL.equals(characteristic.getUuid())) {
                byte[] value = characteristic.getValue();
                handler.post(() -> { if (connection == gatt) battery(value); });
            }
        }
    };
}
