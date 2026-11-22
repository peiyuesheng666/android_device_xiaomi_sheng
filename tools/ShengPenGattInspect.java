// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.diagnostics;

import android.bluetooth.*;
import android.content.Context;
import android.os.Handler;
import java.util.ArrayDeque;
import java.util.UUID;
import java.util.function.Consumer;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import android.hardware.input.InputManager;
import android.view.InputDevice;
import android.os.IBinder;
import org.lineageos.sheng.stylus.PenModel;
import org.lineageos.sheng.stylus.MippProfile;

/** Information queries by default; explicit opt-in enables a bounded MIPP trial. */
final class ShengPenGattInspect extends BluetoothGattCallback {
    private static UUID standard(String id) {
        return UUID.fromString("0000" + id + "-0000-1000-8000-00805f9b34fb");
    }
    private static final UUID SERVICE = UUID.fromString("0000fe10-aa6c-462a-964a-7f2ed5b3e512");
    private static final UUID COMMAND = UUID.fromString("0000fe11-aa6c-462a-964a-7f2ed5b3e512");
    private static final UUID REPLY = UUID.fromString("0000fe12-aa6c-462a-964a-7f2ed5b3e512");
    private static final UUID CCCD = standard("2902"), PNP = standard("2a50");
    private final Handler handler;
    private final ArrayDeque<BluetoothGattCharacteristic> reads = new ArrayDeque<>();
    private BluetoothGatt client;
    private BluetoothGattCharacteristic command, reply;
    private boolean closed, identityVerified, writeDone;
    private byte[] pendingReply;
    private int opcode;
    private final boolean initialize = "1".equals(System.getenv("SHENG_PEN_INITIALIZE"));
    private boolean touchOwned, second, ready;
    private int expectedOpcode, expectedLength, id, touchType;
    private PenModel model;
    private byte[] localAddress;
    private Consumer<byte[]> nextReply;
    private final Set<Integer> disabledInputs = new HashSet<>();
    private Context context;
    private Runnable timeout;
    private boolean mtuPending;
    private Runnable trialTimeout;
    private boolean writingWindowStarted;
    private ShengPenPanelObserver panelObserver;
    private final ArrayDeque<Integer> panelRequests=new ArrayDeque<>();
    private final boolean initializationOnly="1".equals(System.getenv("SHENG_PEN_INITIALIZATION_ONLY"));
    private final boolean motionHandshake="1".equals(System.getenv("SHENG_PEN_PANEL_MOTION"));
    private int pendingMotion=-1;
    private final boolean subscribePressure="1".equals(System.getenv("SHENG_PEN_REPORT5_SUBSCRIBE"));
    private final ArrayDeque<BluetoothGattDescriptor> reportReferences=new ArrayDeque<>();
    private BluetoothGattCharacteristic pressureReport;
    private BluetoothGattDescriptor pressureCccd;
    private boolean pressureSubscriptionPending;
    private boolean pressureSetupPending, pressureAwaitingUndock;
    private final boolean subscribeAfterUndock="1".equals(System.getenv("SHENG_PEN_SUBSCRIBE_AFTER_UNDOCK"));

    private ShengPenGattInspect(Handler handler) { this.handler = handler; }

    static void start(Context context, BluetoothDevice device, Handler handler) {
        if (device.getBondState() != BluetoothDevice.BOND_BONDED)
            throw new IllegalStateException("Information probe requires an already bonded pen");
        ShengPenGattInspect probe = new ShengPenGattInspect(handler);
        probe.context = context;
        if (probe.initialize) {
            String local = context.getSystemService(BluetoothManager.class).getAdapter().getAddress();
            if (!BluetoothAdapter.checkBluetoothAddress(local) || local.equals("02:00:00:00:00:00"))
                throw new IllegalStateException("Actual local Bluetooth address unavailable");
            probe.localAddress = new byte[6];
            String[] pieces = local.split(":");
            for (int i=0;i<6;i++) probe.localAddress[i]=(byte)Integer.parseInt(pieces[i],16);
        }
        log("Opening information-only GATT for " + device.getAddress());
        probe.client = device.connectGatt(context, false, probe, BluetoothDevice.TRANSPORT_LE);
        if (probe.client == null) probe.finish("connectGatt rejected");
        else {
            probe.timeout = () -> probe.finish("information probe timeout");
            handler.postDelayed(probe.timeout, 45000);
        }
    }

    private static void log(String value) { System.out.println(value); System.out.flush(); }
    private void finish(String reason) {
        if (closed) return;
        closed = true;
        if(panelObserver!=null)panelObserver.close();
        log("GATT inspect done: " + reason);
        if (client != null) { client.disconnect(); client.close(); }
        if (touchOwned) {
            log("Restore ready=" + touch("ready",0) + " disconnect=" + touch("disconnect",touchType));
        }
        try {
            InputManager manager=context.getSystemService(InputManager.class);
            for (int input : disabledInputs) {
                InputDevice device=manager.getInputDevice(input);
                if (device!=null && device.getVendorId()==34 && device.getProductId()==20609)
                    inputOperation("enableInputDevice", input);
            }
        }
        catch (Exception error) { log("Input restoration failed: " + error); }
        System.exit(reason.equals("information queries complete") || reason.equals("trial finished") ? 0 : 1);
    }

    @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
        handler.post(() -> {
            if (closed || g != client) return;
            log("GATT connection status=" + status + " state=" + state);
            if (status == 0 && state == BluetoothProfile.STATE_CONNECTED) {
                if (!g.discoverServices()) finish("discovery rejected");
            } else finish("GATT disconnected/status=" + status);
        });
    }

    @Override public void onServicesDiscovered(BluetoothGatt g, int status) {
        handler.post(() -> {
            if (closed || g != client) return;
            if (status != 0) { finish("service discovery status=" + status); return; }
            for (BluetoothGattService service : g.getServices()) {
                log("Service " + service.getUuid());
                for (BluetoothGattCharacteristic c : service.getCharacteristics())
                    log("  Characteristic " + c.getUuid() + " properties=" + c.getProperties());
            }
            BluetoothGattService mipp = g.getService(SERVICE);
            command = mipp == null ? null : mipp.getCharacteristic(COMMAND);
            reply = mipp == null ? null : mipp.getCharacteristic(REPLY);
            addRead(standard("180a"), PNP);
            addRead(standard("180a"), standard("2a28"));
            addRead(standard("180f"), standard("2a19"));
            readNext();
        });
    }

    private void addRead(UUID serviceId, UUID id) {
        BluetoothGattService service = client.getService(serviceId);
        BluetoothGattCharacteristic value = service == null ? null : service.getCharacteristic(id);
        if (value != null) reads.add(value);
    }
    private void readNext() {
        if (!reads.isEmpty()) {
            if (!client.readCharacteristic(reads.peek())) finish("read rejected");
            return;
        }
        if (!identityVerified) { finish("PnP identity not a supported Focus Pen"); return; }
        if (command == null || reply == null) { finish("MIPP characteristics missing"); return; }
        BluetoothGattDescriptor descriptor = reply.getDescriptor(CCCD);
        if (descriptor == null || !client.setCharacteristicNotification(reply, true)) {
            finish("MIPP notification unavailable"); return;
        }
        int result = client.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
        if (result != BluetoothStatusCodes.SUCCESS) finish("CCCD submission=" + result);
    }

    @Override public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c,
            byte[] value, int status) {
        handler.post(() -> {
            if (closed || g != client || reads.peek() != c) return;
            log("Read " + c.getUuid() + " status=" + status + " hex=" + hex(value));
            if (status == 0 && c.getUuid().equals(PNP) && value.length == 7) {
                int source = value[0] & 255;
                int vendor = (value[1] & 255) | ((value[2] & 255) << 8);
                int product = (value[3] & 255) | ((value[4] & 255) << 8);
                model = PenModel.fromPnp(value);
                identityVerified = model != null;
                log("PnP source=" + source + " vendor=" + vendor + " product=" + product
                        + " supportedFocus=" + identityVerified);
                touchType = model == null ? 0 : model.touchType;
            }
            reads.remove();
            readNext();
        });
    }

    @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) {
        handler.post(() -> {
            if (closed || g != client || !d.getUuid().equals(CCCD)) return;
            if(d==pressureCccd && pressureSubscriptionPending) {
                pressureSubscriptionPending=false;
                log("PRESSURE_REPORT5_SUBSCRIPTION status="+status);
                if(status!=0) {finish("pressure notification subscription rejected");return;}
                pressureSetupPending=false;
                if(trialTimeout==null)openWritingWindow();
                else {log("PRESSURE_REPORT5_READY_AFTER_UNDOCK");drainPanelRequests();}
                return;
            }
            if(d.getCharacteristic()!=reply)return;
            if (status != 0) finish("CCCD status=" + status);
            else if (initialize) {
                requestInitializationMtu();
            } else query();
        });
    }

    private void requestInitializationMtu() {
        mtuPending=true;
        if(!client.requestMtu(512))finish("MTU request rejected");
    }
    private void startPressureSubscription() {
        pressureSetupPending=true;
        if(model!=PenModel.PRO) {finish("Pro-only pressure subscription requested for another model");return;}
        BluetoothGattService hid=client.getService(standard("1812"));
        if(hid==null) {finish("HID service unavailable for pressure subscription");return;}
        for(BluetoothGattCharacteristic c:hid.getCharacteristics()) {
            if(!c.getUuid().equals(standard("2a4d")))continue;
            BluetoothGattDescriptor reference=c.getDescriptor(standard("2908"));
            if(reference!=null)reportReferences.add(reference);
        }
        readPressureReference();
    }
    private void readPressureReference() {
        if(!reportReferences.isEmpty()) {
            if(!client.readDescriptor(reportReferences.peek()))finish("HID report reference read rejected");
            return;
        }
        if(pressureReport==null || (pressureReport.getProperties()&BluetoothGattCharacteristic.PROPERTY_NOTIFY)==0) {
            finish("Exact input report 5 unavailable");return;
        }
        pressureCccd=pressureReport.getDescriptor(CCCD);
        if(pressureCccd==null || !client.setCharacteristicNotification(pressureReport,true)) {
            finish("Pressure notification registration rejected");return;
        }
        if(subscribeAfterUndock && dock()==0) {
            pressureSetupPending=false;pressureAwaitingUndock=true;
            log("PRESSURE_REPORT5_REGISTERED; awaiting physical undock before CCCD write");
            openWritingWindow();return;
        }
        writePressureCccd();
    }
    private void writePressureCccd() {
        // Enable the standard report-5 CCCD for this connected pen. Its previous
        // value cannot be read on this firmware; never invent a previous value
        // or write zero on exit while HidHost owns the same physical link.
        pressureSubscriptionPending=true;
        int result=client.writeDescriptor(pressureCccd,BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
        if(result!=BluetoothStatusCodes.SUCCESS)finish("Pressure CCCD submission="+result);
    }
    @Override public void onDescriptorRead(BluetoothGatt g,BluetoothGattDescriptor d,int status,byte[] value) {
        handler.post(() -> {
            if(closed || g!=client || reportReferences.peek()!=d)return;
            if(status!=0 || value==null || value.length!=2) {finish("HID report reference unavailable");return;}
            log("PRESSURE_REFERENCE instance="+d.getCharacteristic().getInstanceId()+" value="+hex(value));
            if(value[0]==5 && value[1]==1) {
                if(pressureReport!=null) {finish("Ambiguous input report 5");return;}
                pressureReport=d.getCharacteristic();
            }
            reportReferences.remove();readPressureReference();
        });
    }
    @Override public void onMtuChanged(BluetoothGatt g,int mtu,int status) {
        handler.post(() -> {
            if (closed || g!=client || !mtuPending) return;
            mtuPending=false;
            log("MIPP MTU="+mtu+" status="+status);
            if (status!=0 || mtu<35) finish("MIPP MTU too small"); else query();
        });
    }
    private void query() {
        exchange(new byte[]{(byte)opcode,0}, new int[]{1,2,2,3}[opcode], value -> {
            if (++opcode == 4) {
                if (initialize) beginInitialization(); else finish("information queries complete");
            } else query();
        });
    }
    private void exchange(byte[] bytes, int length, Consumer<byte[]> next) {
        writeDone = false;
        pendingReply = null;
        expectedOpcode = bytes[0] & 255;
        expectedLength = length;
        nextReply = next;
        log("MIPP command=" + hex(bytes));
        int writeType = (command.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0
                ? BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                : BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE;
        int result = client.writeCharacteristic(command, bytes,
                writeType);
        if (result != BluetoothStatusCodes.SUCCESS) finish("MIPP query submission=" + result);
    }
    @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
        handler.post(() -> {
            if (closed || g != client || c != command) return;
            if (status != 0) { finish("MIPP query write status=" + status); return; }
            writeDone = true;
            advance();
        });
    }
    @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) {
        handler.post(() -> {
            if (closed || g != client) return;
            if(c==pressureReport) {
                log("PRESSURE_GATT_REPORT5 length="+value.length+" hex="+hex(value)
                        + " pressure_le16="+(value.length>=2 ? (value[0]&255)|((value[1]&255)<<8) : -1));
                return;
            }
            if(c!=reply)return;
            log("MIPP notification=" + hex(value));
            if (initialize && touchOwned && value.length==3 && (value[0]&255)==0x53
                    && value[1]==1 && (value[2]==0 || value[2]==1)) {
                if (!touch("active",value[2]&255)) finish("pen active mode rejected");
                return;
            }
            if (nextReply == null) return;
            if (value.length < 2 || (value[0] & 255) != (expectedOpcode | 128)) return;
            int length = expectedLength;
            if (value.length != length + 2 || (value[1] & 255) != length) {
                finish("malformed information reply"); return;
            }
            pendingReply = value.clone();
            advance();
        });
    }
    private void advance() {
        if (!writeDone || pendingReply == null) return;
        byte[] reply = pendingReply;
        pendingReply = null;
        Consumer<byte[]> next = nextReply;
        nextReply = null;
        next.accept(reply);
        drainPanelRequests();
    }

    private boolean touch(String operation, int value) {
        try {
            Process process = new ProcessBuilder("/data/local/tmp/sheng-pen-touchctl-probe",
                    operation, Integer.toString(value)).redirectErrorStream(true).start();
            if (!process.waitFor(3, java.util.concurrent.TimeUnit.SECONDS)) {
                process.destroyForcibly(); return false;
            }
            byte[] output = new byte[2048];
            int count = process.getInputStream().read(output);
            if (count > 0) log(new String(output,0,count,StandardCharsets.UTF_8).trim());
            return process.exitValue() == 0;
        } catch (Exception error) { log("Touch operation failed: " + error); return false; }
    }
    private void beginInitialization() {
        try {
            InputManager manager = context.getSystemService(InputManager.class);
            for (int input : manager.getInputDeviceIds()) {
                InputDevice device = manager.getInputDevice(input);
                if (device == null || device.getVendorId()!=34 || device.getProductId()!=20609) continue;
                if ((Boolean)InputDevice.class.getMethod("isEnabled").invoke(device)) {
                    inputOperation("disableInputDevice",input);
                    disabledInputs.add(input);
                }
            }
        } catch (Exception error) { finish("Cannot guard Pro HID reports: " + error); return; }
        panelObserver=new ShengPenPanelObserver(handler,this::panelRequest);
        try {panelObserver.start();}
        catch(RuntimeException error) {finish("panel observer unavailable: "+error);return;}
        if (!touch("connect",touchType)) { finish("pen connect mode rejected"); return; }
        touchOwned=true;
        log("TOUCH_CONNECT_ACQUIRED type="+touchType);
        // Pro reports active state on request; it need not emit a new 0x53
        // notification if already awake when this GATT session starts.
        if (touchType==8) exchange(new byte[]{0x52,0},1,value -> {
            int active=value[2]&255;
            if (active>1 || !touch("active",active)) {
                finish("pen active query rejected"); return;
            }
            assignId();
        });
        else assignId();
    }
    private void inputOperation(String method, int input) throws Exception {
        IBinder binder = (IBinder)Class.forName("android.os.ServiceManager")
                .getMethod("getService",String.class).invoke(null,"input");
        Object api = Class.forName("android.hardware.input.IInputManager$Stub")
                .getMethod("asInterface",IBinder.class).invoke(null,binder);
        Class.forName("android.hardware.input.IInputManager").getMethod(method,int.class).invoke(api,input);
    }
    private void assignId() {
        exchange(new byte[]{4,0},1,value -> {
            id=value[2]&255;
            if (!touch("id", (id<<8)|(second?3:1))) { finish("pen ID rejected"); return; }
            exchange(parameters(second),0,v -> exchange(MippProfile.frequency(id,0),0,v2 ->
                    exchange(MippProfile.voltage(id),0,v3 -> {
                        if (!second) { second=true; assignId(); }
                        else finishInitialization();
                    })));
        });
    }
    private byte[] parameters(boolean secondPhase) {
        return MippProfile.parameters(localAddress,id,secondPhase);
    }
    private void finishInitialization() {
        long seconds=System.currentTimeMillis()/1000;
        exchange(MippProfile.timestamp(seconds),0,v ->
                exchange(new byte[]{0x51,1,(byte)dock()},0,v2 -> {
                    // Piano's reviewed P81C/Pro path sends the real panel state
                    // after initialization; ordinary Focus Pen does not use it.
                    if(model==PenModel.PRO) exchange(MippProfile.proScreenState(model,true),0,v3 -> readyForTrial());
                    else readyForTrial();
                }));
    }
    private void readyForTrial() {
        if (!touch("ready",1)) { finish("pen ready mode rejected"); return; }
        ready=true;
        // Stock worker 2021 -> h2 -> B4 sends the default first-phase profile
        // again after the dual-ID phase returns to 1. Keep sheng's 32-byte
        // profile; neither the current panel FPS nor piano selects 34 bytes.
        exchange(parameters(false),0,v -> {
            log("POST_INIT_TIMING_ACK id="+id);
            // Check the pressure CCCD only after the normal MIPP ready/timing
            // handshake. The pre-initialization write was rejected by the pen.
            if(subscribePressure) startPressureSubscription();
            else openWritingWindow();
        });
    }
    private void openWritingWindow() {
        log("MIPP INITIALIZATION ACKNOWLEDGED; writing remains to be tested");
        handler.removeCallbacks(timeout);
        trialTimeout=() -> finish("trial finished");
        handler.postDelayed(trialTimeout,initializationOnly?5000:600000);
        followDock();
        drainPanelRequests();
    }
    private void panelRequest(int value) {
        if(closed)return;
        int opcode=(value>>>16)&255,panelId=(value>>>8)&255,operation=value&255;
        log("PANEL_REQUEST value="+value+" opcode="+opcode+" id="+panelId+" operation="+operation);
        // The additional stock Pro move/up handshake is opt-in until a real
        // pressure trial qualifies it. Keep only the latest pending state.
        if(motionHandshake && model==PenModel.PRO && opcode==0x35 && operation<=1) {
            pendingMotion=operation;drainPanelRequests();return;
        }
        if(opcode!=0x31 || operation>3)return;
        if(panelRequests.size()>=8) {finish("panel frequency queue overflow");return;}
        panelRequests.add(value);drainPanelRequests();
    }
    private void drainPanelRequests() {
        if(closed || !ready || nextReply!=null || pressureSetupPending || pressureSubscriptionPending)return;
        if(panelRequests.isEmpty()) {
            if(motionHandshake && pendingMotion>=0) {
                int state=pendingMotion;pendingMotion=-1;
                exchange(MippProfile.proMotionState(model,state),0,v ->
                    log("PANEL_MOTION_APPLIED operation="+state));
            }
            return;
        }
        int value=panelRequests.remove(),panelId=(value>>>8)&255,index=value&255;
        byte[] command=MippProfile.frequency(panelId,index);
        exchange(command,0,v -> {
            if(!touch("frequency-ack",49)) {finish("panel frequency acknowledgement rejected");return;}
            log("PANEL_FREQUENCY_APPLIED id="+panelId+" index="+index);
        });
    }
    private int lastDock=-1;
    private int dock() {
        try {
            String a=new String(Files.readAllBytes(Paths.get("/sys/class/qcom-battery/pen_hall3")),StandardCharsets.UTF_8).trim();
            String b=new String(Files.readAllBytes(Paths.get("/sys/class/qcom-battery/pen_hall4")),StandardCharsets.UTF_8).trim();
            return (a.equals("0") || b.equals("0")) ? 0 : 1;
        } catch (Exception error) { return 1; }
    }
    private void followDock() {
        if (closed || !ready) return;
        int current=dock();
        if (current==1 && !writingWindowStarted && !initializationOnly) {
            writingWindowStarted=true;
            handler.removeCallbacks(trialTimeout);
            handler.postDelayed(trialTimeout,180000);
            log("PHYSICAL UNDOCK; bounded writing window started");
        }
        if (nextReply==null && !pressureSubscriptionPending && current!=lastDock) {
            lastDock=current;
            exchange(new byte[]{0x51,1,(byte)current},0,v -> {});
        } else if (nextReply==null && !pressureSubscriptionPending && current==1 && pressureAwaitingUndock) {
            pressureAwaitingUndock=false;
            log("PRESSURE_SUBSCRIBE_AFTER_UNDOCK");
            writePressureCccd();
        }
        handler.postDelayed(this::followDock,1000);
    }
    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte b : bytes) result.append(String.format("%02x", b & 255));
        return result.toString();
    }
}
