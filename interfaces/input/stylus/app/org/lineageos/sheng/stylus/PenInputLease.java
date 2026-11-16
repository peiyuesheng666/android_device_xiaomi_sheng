// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.content.Context;
import android.hardware.input.IInputManager;
import android.os.ServiceManager;
import android.provider.Settings;
import android.util.AtomicFile;
import android.view.InputDevice;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** A durable restoration journal for exact Pro inputs previously enabled by Android. */
final class PenInputLease {
    private final AtomicFile journal;
    private final int boot;
    private final IInputManager input;
    private final List<JSONObject> debts = new ArrayList<>();

    PenInputLease(Context context) throws Exception {
        boot = Settings.Global.getInt(context.getContentResolver(), Settings.Global.BOOT_COUNT, -1);
        if (boot < 0) throw new IllegalStateException("Boot generation unavailable");
        journal = new AtomicFile(new File(context.createDeviceProtectedStorageContext()
                .getFilesDir(), "pro-input-lease.json"));
        input = IInputManager.Stub.asInterface(ServiceManager.getService("input"));
        if (input == null) throw new IllegalStateException("Input service unavailable");
        if (journal.exists()) {
            JSONObject saved = new JSONObject(new String(journal.readFully(), StandardCharsets.UTF_8));
            // InputManager's disabled state does not survive a real boot. Never
            // apply a stale input ID/descriptor lease from an earlier boot.
            if (saved.getInt("boot") == boot) {
                JSONArray entries = saved.getJSONArray("entries");
                if (entries.length() > 0 && saved.optInt("version", 1) != 2) {
                    throw new IllegalStateException("Older input journal lacks owned input IDs");
                }
                for (int i = 0; i < entries.length(); i++) debts.add(entries.getJSONObject(i));
            }
        }
        save();
    }

    private void save() throws Exception {
        JSONArray entries = new JSONArray();
        for (JSONObject entry : debts) entries.put(entry);
        byte[] bytes = new JSONObject().put("version", 2).put("boot", boot).put("entries", entries)
                .toString().getBytes(StandardCharsets.UTF_8);
        FileOutputStream stream = journal.startWrite();
        try {
            stream.write(bytes); stream.getFD().sync(); journal.finishWrite(stream);
            if (!Arrays.equals(bytes, journal.readFully())) throw new IllegalStateException("Input journal commit mismatch");
        }
        catch (Exception error) { journal.failWrite(stream); throw error; }
    }

    private static boolean matches(InputDevice device, JSONObject debt) throws Exception {
        return device != null && device.getVendorId() == 34
                && PenModel.fromBluetoothIds(34, device.getProductId()) == PenModel.PRO
                && device.getProductId() == debt.getInt("product")
                && debt.getString("address").equalsIgnoreCase(device.getBluetoothAddress())
                && debt.getString("descriptor").equals(device.getDescriptor());
    }

    boolean restore() throws Exception {
        boolean unresolved = false;
        for (int index = debts.size() - 1; index >= 0; index--) {
            JSONObject debt = debts.get(index);
            JSONArray ids = debt.getJSONArray("ownedIds");
            for (int offset = ids.length() - 1; offset >= 0; offset--) {
                int id = ids.getInt(offset);
                if (id < 0) throw new IllegalStateException("Invalid owned input ID");
                InputDevice device = input.getInputDevice(id);
                if (device != null && !matches(device, debt)) {
                    // An ID reused for a different identity is not authority
                    // to enable that device. Keep its debt until it disappears.
                    unresolved = true; continue;
                }
                // InputManager retains disabled IDs even after node removal.
                // Always clear our exact ID, including when InputReader still
                // reports enabled before an asynchronous disable has applied.
                input.enableInputDevice(id);
                InputDevice current = input.getInputDevice(id);
                if (current != null && (!matches(current, debt) || !current.isEnabled())) {
                    unresolved = true; continue;
                }
                ids.remove(offset); save();
            }
            if (ids.length() == 0) { debts.remove(index); save(); }
        }
        return !unresolved;
    }

    private static boolean ownsId(JSONObject debt, int id) throws Exception {
        if (debt == null) return false;
        JSONArray ids = debt.getJSONArray("ownedIds");
        for (int i = 0; i < ids.length(); i++) if (ids.getInt(i) == id) return true;
        return false;
    }

    boolean guard(PenModel model, int product, String address) throws Exception {
        if (model != PenModel.PRO) return true;
        boolean disabled = true;
        for (int id : input.getInputDeviceIds()) {
            InputDevice device = input.getInputDevice(id);
            if (device == null || device.getVendorId() != 34 || device.getProductId() != product
                    || !address.equalsIgnoreCase(device.getBluetoothAddress())) continue;
            JSONObject owned = null;
            for (JSONObject debt : debts) if (matches(device, debt)) { owned = debt; break; }
            if (!ownsId(owned, id) && device.isEnabled()) {
                // Commit intent before the Binder operation. A crash afterwards
                // leaves exact identity and every ID whose disable we own.
                boolean added = owned == null;
                if (added) {
                    owned = new JSONObject().put("product", product).put("address", address)
                            .put("descriptor", device.getDescriptor()).put("ownedIds", new JSONArray());
                    debts.add(owned);
                }
                JSONArray ids = owned.getJSONArray("ownedIds");
                ids.put(id);
                try { save(); } catch (Exception error) {
                    ids.remove(ids.length() - 1);
                    if (added) debts.remove(owned);
                    throw error;
                }
            }
            if (ownsId(owned, id)) {
                if (device.isEnabled()) input.disableInputDevice(id);
                InputDevice current = input.getInputDevice(id);
                if (current != null && current.isEnabled()) disabled = false;
            }
        }
        return disabled;
    }
}
