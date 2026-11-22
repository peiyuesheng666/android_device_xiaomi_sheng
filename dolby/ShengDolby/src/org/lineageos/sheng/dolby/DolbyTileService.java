// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.dolby;

import android.graphics.drawable.Icon;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** Optional QS control; reflects the retained DAP controller's verified state. */
public final class DolbyTileService extends TileService {
    private AtmosApplication controller;
    private boolean pending;
    private long pendingVersion;
    private final java.util.function.Consumer<AtmosApplication.State> listener = state -> {
        if (state.version > pendingVersion) pending = false;
        refresh(state);
    };

    @Override public void onStartListening() {
        super.onStartListening();
        Object candidate = ((CompatibilityApplication) getApplication()).controller();
        if (candidate instanceof AtmosApplication) {
            controller = (AtmosApplication) candidate;
            controller.addListener(listener);
            pending = false;
            refresh(controller.getState());
        } else {
            refresh(null);
        }
    }

    @Override public void onStopListening() {
        if (controller != null) controller.removeListener(listener);
        super.onStopListening();
    }

    @Override public void onDestroy() {
        if (controller != null) controller.removeListener(listener);
        super.onDestroy();
    }

    @Override public void onClick() {
        super.onClick();
        Runnable toggle = () -> {
            if (controller == null || pending) return;
            AtmosApplication.State state = controller.getState();
            if (!state.ready || state.failed) { refresh(state); return; }
            pending = true;
            pendingVersion = state.version;
            controller.setRequested(!state.active);
        };
        if (isLocked()) unlockAndRun(toggle);
        else toggle.run();
    }

    private void refresh(AtmosApplication.State state) {
        Tile tile = getQsTile();
        if (tile == null) return;
        tile.setLabel(getString(R.string.app_name));
        tile.setIcon(Icon.createWithResource(this, R.drawable.ic_dolby_qs));
        tile.setState(state == null || !state.ready || state.failed ? Tile.STATE_UNAVAILABLE
                : state.active ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        tile.updateTile();
    }
}
