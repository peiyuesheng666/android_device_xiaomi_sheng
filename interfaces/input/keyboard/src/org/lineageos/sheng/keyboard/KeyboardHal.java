// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.os.Handler;
import android.os.HwBinder;
import android.os.HwBlob;
import android.os.HwParcel;
import android.os.IHwBinder;
import android.os.RemoteException;
import android.util.Log;
import java.util.ArrayList;
import java.util.Arrays;

/** HIDL 1.0 client for the unmodified sheng keyboardnanoapp service. */
final class KeyboardHal {
    private static final String SERVICE = "vendor.xiaomi.hardware.keyboardnanoapp@1.0::IKeyboardNanoapp";
    private static final String CALLBACK = "vendor.xiaomi.hardware.keyboardnanoapp@1.0::INanoappCallback";
    private static final String BASE = "android.hidl.base@1.0::IBase";
    // Frozen ABI fingerprints from the original sheng interface, not authentication material.
    private static final String[] HASHES = {
        "328ea9e1f8f306f790e9001518d3695f80a00922bb946958ecd9c78a3c530da4",
        "ec7fd79ed02dfa85bc499426adae3ebe23ef0524f3cd6957139324b83b18ca4c"
    };
    interface Listener { void onReply(byte[] reply); void onTransportLost(); }
    private final Handler handler;
    private final Listener listener;
    private IHwBinder service;
    private long generation;
    private final IHwBinder.DeathRecipient death = this::onBinderDied;
    private void onBinderDied(long cookie) {
        synchronized (KeyboardHal.this) {
            if (cookie != generation) return;
            service = null;
        }
        handler.post(() -> listener.onTransportLost());
    }

    KeyboardHal(Handler handler, Listener listener) { this.handler = handler; this.listener = listener; }

    synchronized boolean connect() {
        if (service != null) return true;
        IHwBinder candidate = null;
        try {
            candidate = HwBinder.getService(SERVICE, "default", false);
            if (candidate == null) return false;
            final long epoch = ++generation;
            if (!candidate.linkToDeath(death, epoch)) return false;
            HwParcel data = new HwParcel(), reply = new HwParcel();
            try {
                data.writeInterfaceToken(SERVICE);
                data.writeStrongBinder(new Callback(epoch));
                candidate.transact(2, data, reply, 0);
                reply.verifySuccess();
            } finally { data.releaseTemporaryStorage(); reply.release(); }
            service = candidate;
            Log.i("ShengKeyboard", "Original keyboard HIDL connected");
            return true;
        } catch (RemoteException | RuntimeException error) {
            if (candidate != null) {
                try { candidate.unlinkToDeath(death); } catch (RuntimeException ignored) {}
            }
            return false;
        }
    }

    synchronized boolean send(byte[] packet) {
        if (packet.length != 68 || service == null) return false;
        HwParcel data = new HwParcel(), reply = new HwParcel();
        try {
            data.writeInterfaceToken(SERVICE);
            ArrayList<Byte> bytes = new ArrayList<>(packet.length);
            for (byte value : packet) bytes.add(value);
            data.writeInt8Vector(bytes);
            service.transact(1, data, reply, 0);
            reply.verifySuccess();
            return reply.readInt32() == 66;
        } catch (RemoteException | RuntimeException error) {
            service = null;
            ++generation;
            handler.post(() -> listener.onTransportLost());
            return false;
        } finally { data.releaseTemporaryStorage(); reply.release(); }
    }

    private void receive(byte[] buffer, long epoch) {
        synchronized (this) { if (epoch != generation || service == null) return; }
        int pos = 0;
        while (pos + 2 <= buffer.length) {
            int length = buffer[pos + 1] & 0xff;
            if (buffer[pos] != (byte) 0xaa || length == 0 || pos + 2 + length > buffer.length) return;
            byte[] reply = Arrays.copyOfRange(buffer, pos + 2, pos + 2 + length);
            if (KeyboardProtocol.validReply(reply)) listener.onReply(reply);
            pos += length + 2;
        }
    }

    private final class Callback extends HwBinder {
        private final long epoch;
        Callback(long epoch) { this.epoch = epoch; }
        @Override public android.os.IHwInterface queryLocalInterface(String descriptor) { return null; }
        @Override public boolean linkToDeath(IHwBinder.DeathRecipient recipient, long cookie) { return true; }
        @Override public boolean unlinkToDeath(IHwBinder.DeathRecipient recipient) { return true; }
        @Override public void onTransact(int code, HwParcel data, HwParcel reply, int flags)
                throws RemoteException {
            boolean oneWay = (flags & 1) != 0;
            if (code == 1 || code == 2) {
                if (!oneWay) { reply.writeStatus(Integer.MIN_VALUE); reply.send(); return; }
                data.enforceInterface(CALLBACK);
                if (code == 1) {
                    ArrayList<Byte> input = data.readInt8Vector();
                    if (input.size() > 4096) return;
                    byte[] bytes = new byte[input.size()];
                    for (int i = 0; i < bytes.length; ++i) bytes[i] = input.get(i);
                    handler.post(() -> receive(bytes, epoch));
                } else {
                    final int error = data.readInt32();
                    handler.post(() -> Log.w("ShengKeyboard", "Keyboard HAL error=" + error));
                }
                return;
            }
            data.enforceInterface(BASE);
            if (code == 256462420 || code == 257120595) return; // instrumentation / property notification
            if (oneWay) return;
            reply.writeStatus(0);
            switch (code) {
                case 256067662:
                    reply.writeStringVector(new ArrayList<>(Arrays.asList(CALLBACK, BASE))); break;
                case 256136003: reply.writeString(CALLBACK); break;
                case 256131655: data.readNativeHandle(); data.readStringVector(); break;
                case 256921159: break; // ping
                case 256398152: {
                    HwBlob header = new HwBlob(16), hashes = new HwBlob(64);
                    header.putInt32(8, 2); header.putBool(12, false);
                    for (int h = 0; h < HASHES.length; ++h) {
                        byte[] bytes = new byte[32];
                        for (int i = 0; i < 32; ++i) bytes[i] = (byte) Integer.parseInt(HASHES[h].substring(i * 2, i * 2 + 2), 16);
                        hashes.putInt8Array(h * 32, bytes);
                    }
                    header.putBlob(0, hashes); reply.writeBuffer(header); break;
                }
                case 257049926: {
                    HwBlob debug = new HwBlob(24);
                    debug.putInt32(0, android.os.Process.myPid());
                    debug.putInt64(8, 0); debug.putInt32(16, 0);
                    reply.writeBuffer(debug); break;
                }
                default: return;
            }
            reply.send();
        }
    }
}
