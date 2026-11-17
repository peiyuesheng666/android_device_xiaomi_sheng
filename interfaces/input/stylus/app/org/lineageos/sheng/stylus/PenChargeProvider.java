// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Bundle;
import org.lineageos.sheng.pen.charge.ChargeStatus;
import org.lineageos.sheng.pen.charge.PenDockPeer;

/** Read-only charger status and signature-protected window visibility; no hardware writes. */
public final class PenChargeProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    @Override public Bundle call(String method, String argument, Bundle extras) {
        getContext().enforceCallingOrSelfPermission("org.lineageos.sheng.stylus.READ_CHARGING", "Pen page visibility");
        if (!"settings_visibility".equals(method) || extras == null)
            throw new IllegalArgumentException("Unsupported presentation call");
        PenPopupVisibility.setVisible(extras.getBinder("window"), extras.getBoolean("visible"));
        return Bundle.EMPTY;
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        if (selection != null || args != null || order != null)
            throw new IllegalArgumentException("Unsupported charging query");
        if ("/dock".equals(uri.getPath())) {
            MatrixCursor cursor = new MatrixCursor(new String[]{"address"}, 1);
            cursor.addRow(new Object[]{PenDockPeer.read()});
            return cursor;
        }
        if (!"/status".equals(uri.getPath())) throw new IllegalArgumentException("Unsupported charging query");
        ChargeStatus status = PenChargingState.read();
        MatrixCursor cursor = new MatrixCursor(new String[]{"state", "level", "address"}, 1);
        cursor.addRow(new Object[]{status.state.name(), status.level, status.address});
        return cursor;
    }
    @Override public String getType(Uri uri) { return "vnd.android.cursor.item/vnd.sheng.pen-charge"; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException("Read only"); }
    @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException("Read only"); }
    @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException("Read only"); }
}
