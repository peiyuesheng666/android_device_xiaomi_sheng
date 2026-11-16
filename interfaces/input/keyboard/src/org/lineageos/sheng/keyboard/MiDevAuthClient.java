// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Parcel;
import android.os.RemoteException;
import android.os.UserManager;
import android.util.Log;

/** Calls the original APK's first four AIDL methods; never replaces its decisions. */
final class MiDevAuthClient {
    private static final String DESCRIPTOR = "com.xiaomi.devauth.IMiDevAuthInterface";
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable ready;
    private volatile IBinder service;
    private boolean bound;
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            service = binder; ready.run();
        }
        @Override public void onServiceDisconnected(ComponentName name) { service = null; }
        @Override public void onBindingDied(ComponentName name) { rebind(); }
        @Override public void onNullBinding(ComponentName name) { rebind(); }
    };
    MiDevAuthClient(Context context, Runnable ready) { this.context = context; this.ready = ready; }
    void bind() { main.post(this::bindOnMain); }
    private void bindOnMain() {
        if (bound || !context.getSystemService(UserManager.class).isUserUnlocked()) return;
        Intent intent = new Intent().setComponent(new ComponentName("com.xiaomi.devauth",
                "com.xiaomi.devauth.MiDevAuthService"));
        try { bound = context.bindService(intent, connection, Context.BIND_AUTO_CREATE); }
        catch (RuntimeException error) {
            Log.w("ShengKeyboard", "Cannot bind original MiDev service: " + error.getClass().getSimpleName());
        }
    }
    private void rebind() {
        service = null;
        if (bound) {
            try { context.unbindService(connection); } catch (IllegalArgumentException ignored) {}
        }
        bound = false;
        main.removeCallbacks(retry);
        main.postDelayed(retry, 5000);
    }
    private final Runnable retry = this::bindOnMain;
    boolean available() { return service != null; }

    // Method numbers and parcel layout are the frozen OEM AIDL ABI.
    byte[] challenge() throws RemoteException { return call(1, 16, null).createByteArrayAndClose(); }
    byte[] choose(byte[] uid, byte[] first, byte[] second) throws RemoteException {
        return call(2, null, new byte[][]{uid, first, second}).createByteArrayAndClose();
    }
    int verify(byte[] uid, byte[] key, byte[] challenge, byte[] token) throws RemoteException {
        Result result = call(3, 1, new byte[][]{uid, key, challenge, token});
        try { return result.parcel.readInt(); } finally { result.parcel.recycle(); }
    }
    byte[] token(byte[] uid, byte[] key, byte[] challenge) throws RemoteException {
        return call(4, 1, new byte[][]{uid, key, challenge}).createByteArrayAndClose();
    }
    private Result call(int code, Integer first, byte[][] arrays) throws RemoteException {
        IBinder target = service;
        if (target == null) throw new RemoteException("Original authentication service unavailable");
        Parcel data = Parcel.obtain(), reply = Parcel.obtain();
        try {
            data.writeInterfaceToken(DESCRIPTOR);
            if (first != null) data.writeInt(first);
            if (arrays != null) for (byte[] value : arrays) data.writeByteArray(value);
            if (!target.transact(code, data, reply, 0)) throw new RemoteException("Unsupported auth transaction");
            reply.readException();
            return new Result(reply);
        } catch (RemoteException | RuntimeException error) {
            reply.recycle(); throw error;
        } finally { data.recycle(); }
    }
    private static final class Result {
        final Parcel parcel;
        Result(Parcel parcel) { this.parcel = parcel; }
        byte[] createByteArrayAndClose() {
            try { return parcel.createByteArray(); } finally { parcel.recycle(); }
        }
    }
}
