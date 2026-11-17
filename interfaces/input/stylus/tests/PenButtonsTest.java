// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.lineageos.sheng.pen.controls.PenControls;
import org.lineageos.sheng.pen.controls.PenControls.Gesture;
import org.lineageos.sheng.pen.controls.PenMenuEntry;

/** Gesture edge, deadline and protocol-boundary checks without synthesizing device input. */
public final class PenButtonsTest {
    private static int checks;
    private static void check(boolean value) { if (!value) throw new AssertionError("check " + checks); checks++; }
    private static void rejects(Runnable operation) {
        try { operation.run(); } catch (IllegalArgumentException expected) { checks++; return; }
        throw new AssertionError("Invalid control packet accepted");
    }
    private static byte[] report(int usage) { return new byte[] {(byte) usage}; }
    public static void main(String[] args) {
        List<String> events = new ArrayList<>();
        PenButtonState state = new PenButtonState(new PenButtonState.Listener() {
            public void down(Gesture gesture) { events.add("down " + gesture); }
            public void up(Gesture gesture) { events.add("up " + gesture); }
        });
        check(state.accept(report(0x6e), 100));
        check(events.equals(Arrays.asList("down SQUEEZE")));
        for (int i = 0; i < 100; i++) state.accept(report(0x6e), 110 + i);
        check(events.size() == 1);
        state.accept(report(0), 400); state.accept(report(0), 401);
        check(events.equals(Arrays.asList("down SQUEEZE", "up SQUEEZE")));
        state.accept(report(0x6e), 500); state.clear(); state.accept(report(0), 501);
        check(events.size() == 3);
        state.accept(report(0x6e), 600); check(events.size() == 4);
        state.clear(); events.clear();

        // A quick side-button click is not a long press, and repeated reports
        // must not move the original deadline into the future.
        state.accept(report(0x4e), 1000); state.held(1379); check(events.isEmpty());
        state.accept(report(0), 1379); state.held(1500); check(!events.contains("down PRIMARY"));
        state.clear(); events.clear(); state.accept(report(0x4e), 2000);
        state.accept(report(0x4e), 2300); check(state.holdDelay(2300) == 80);
        state.held(2380); state.held(2390); check(events.equals(Arrays.asList("down PRIMARY")));
        check(state.holdDelay(2400) == -1);
        state.accept(report(0), 2500); check(events.equals(Arrays.asList("down PRIMARY", "up PRIMARY")));
        state.clear(); events.clear(); state.accept(report(0x4b), 3000); state.clear(); state.held(4000);
        check(events.isEmpty());
        state.accept(report(0x4b), 4100); check(!state.accept(report(0x7f), 4120)); state.held(5000);
        check(events.isEmpty());

        // The pressure stream cannot be interpreted as a shortcut.
        for (int size : new int[]{0, 2, 14, 15, 128}) check(!state.accept(new byte[size], 5100));
        check(!state.accept(null, 5100)); check(!state.accept(report(0x6e), -1));
        check(events.isEmpty());
        for (int usage : new int[]{0x5b, 0x61, 0x58}) {
            events.clear();
            Gesture gesture = PenButtonState.gesture(usage);
            check(state.accept(report(usage), 6000));
            check(state.holdDelay(6000) == -1);
            check(state.accept(report(usage), 6010));
            state.held(6400);
            check(events.equals(Arrays.asList("down " + gesture)));
            state.accept(report(0), 6410);
            check(events.equals(Arrays.asList("down " + gesture, "up " + gesture)));
        }
        events.clear();

        check(PenControls.menu(null).length == 6);
        check(Arrays.equals(PenControls.menu("NONE,MENU,BACK,BACK,HOME,invalid"),
                new PenControls.Action[]{PenControls.Action.BACK, PenControls.Action.HOME}));
        check(PenControls.menu("BACK,HOME,RECENTS,MEDIA,SCREENSHOT,SETTINGS,UNDO,REDO").length == 6);
        check(PenControls.menu("").length == 6);
        check(PenControls.level("-1", 2, 4) == 2);
        check(PenControls.level("5", 2, 4) == 2);
        check(PenControls.level("4", 2, 4) == 4);
        check(PenControls.level(null, 3, 5) == 3);
        byte[][] commands = PenFeatureCommands.configure(2, 3);
        check(Arrays.equals(commands[0], new byte[]{0x5f, 1, 1}));
        check(Arrays.equals(commands[1], new byte[]{0x5c, 4, 2, 88, 1, 44}));
        check(Arrays.equals(commands[2], new byte[]{0x5a, 1, 3}));
        check(Arrays.equals(commands[3], new byte[]{0x63, 1, 1}));
        check(Arrays.equals(PenFeatureCommands.haptic(1, 2), new byte[]{0x5e, 2, 1, (byte) 172}));
        check(Arrays.equals(PenFeatureCommands.haptic(2, 4), new byte[]{0x5e, 2, 2, (byte) 248}));
        check(Arrays.equals(PenFeatureCommands.haptic(3, 0), new byte[]{0x5e, 2, 3, (byte) 128}));
        for (int invalid : new int[]{-1, 5, 255}) rejects(() -> PenFeatureCommands.configure(invalid, 3));
        rejects(() -> PenFeatureCommands.configure(2, 6));
        rejects(() -> PenFeatureCommands.haptic(0, 2)); rejects(() -> PenFeatureCommands.haptic(5, 2));
        // A real haptic ACK carries no status byte; an absent ACK is still failure.
        byte[] haptic = PenFeatureCommands.haptic(1,2);
        check(PenFeatureCommands.accepted(haptic,new byte[]{(byte)0xde,0}));
        check(!PenFeatureCommands.accepted(haptic,new byte[0]));
        check(!PenFeatureCommands.accepted(haptic,new byte[]{(byte)0xde,1,1}));
        check(!PenFeatureCommands.accepted(haptic,new byte[]{(byte)0xda,0}));
        check(PenFeatureCommands.accepted(commands[1],new byte[]{(byte)0xdc,1,1}));
        check(!PenFeatureCommands.accepted(commands[1],new byte[]{(byte)0xdc,1,0}));
        check(!PenFeatureCommands.accepted(commands[1],new byte[]{(byte)0xdc,0}));
        // Preserve legacy choices, order, application identity and limits.
        PenMenuEntry app=PenMenuEntry.application("com.example.notes/.Main");
        check(app.component.equals("com.example.notes/com.example.notes.Main"));
        check(app.equals(PenMenuEntry.application("com.example.notes/com.example.notes.Main")));
        check(PenMenuEntry.read(null).length==6);
        check(Arrays.stream(PenMenuEntry.read(null)).anyMatch(item -> item.action==PenControls.Action.LASER));
        check(Arrays.stream(PenMenuEntry.read("BACK,HOME,RECENTS,MEDIA,SCREENSHOT,SETTINGS")).anyMatch(item -> item.action==PenControls.Action.LASER));
        check(PenMenuEntry.read("BACK,HOME").length==2);
        check(PenButtonState.gesture(0x61)==Gesture.SLIDE_UP);
        check(PenButtonState.gesture(0x5b)==Gesture.SLIDE_DOWN);
        check(PenButtonState.gesture(0x58)==Gesture.DOUBLE_TAP);
        PenMenuEntry[] entries=PenMenuEntry.read("BACK,app:com.example.notes/.Main,BACK,NONE,invalid,MENU");
        check(entries.length==2 && entries[0].action==PenControls.Action.BACK && entries[1].equals(app));
        String encoded=PenMenuEntry.write(Arrays.asList(app,PenMenuEntry.operation(PenControls.Action.HOME)));
        check(Arrays.equals(PenMenuEntry.read(encoded),new PenMenuEntry[]{app,PenMenuEntry.operation(PenControls.Action.HOME)}));
        rejects(()->PenMenuEntry.application("intent:#Intent;action=x;end"));
        rejects(()->PenMenuEntry.application("com.test/.Main,HOME"));
        rejects(()->PenMenuEntry.write(Arrays.asList(app,app)));
        rejects(()->PenMenuEntry.write(new ArrayList<>()));
        check(PenMenuEntry.read("BACK,HOME,RECENTS,MEDIA,SCREENSHOT,SETTINGS,UNDO").length==6);
        // A cancelled/multi-touch/horizontal drag must never open settings.
        PenCardGesture card=new PenCardGesture(8,40);
        card.down(100,100);check(card.up(105,106)==PenCardGesture.Result.OPEN);
        card.down(100,100);check(card.up(102,140)==PenCardGesture.Result.OPEN);
        card.down(100,100);check(card.up(100,60)==PenCardGesture.Result.DISMISS);
        card.down(100,100);check(card.up(150,140)==PenCardGesture.Result.NONE);
        card.down(100,100);card.move(100,125);check(card.up(100,100)==PenCardGesture.Result.NONE);
        card.down(100,100);card.cancel();check(card.up(100,160)==PenCardGesture.Result.NONE);
        check(card.up(100,100)==PenCardGesture.Result.NONE);
        // Screen wake protection survives; an unrelated vote/dock transition
        // cannot impose another second after the display has already settled.
        PenWakeGate wake=new PenWakeGate();
        check(!wake.ready(true,true,100));
        check(!wake.ready(true,true,1099));
        check(wake.ready(true,true,1100));
        check(!wake.ready(true,false,1200));
        check(wake.ready(true,true,1201));
        wake.observe(true,2000);
        check(wake.ready(true,true,2001));
        wake.observe(false,2100);
        check(!wake.ready(true,true,2200));
        check(!wake.ready(true,true,3199));
        check(wake.ready(true,true,3200));
        check(!wake.ready(true,true,50));
        check(!wake.ready(false,true,2000));
        check(!wake.ready(true,true,-1));
        state.clear(); events.clear(); state.setSideButtonLongPress(false);
        check(state.accept(report(0x4b), 7000));
        check(events.equals(Arrays.asList("down SECONDARY")));
        check(state.holdDelay(7000) == -1);
        state.accept(report(0x4b), 7050); state.held(7100);
        check(events.equals(Arrays.asList("down SECONDARY")));
        state.accept(report(0), 7130);
        check(events.equals(Arrays.asList("down SECONDARY", "up SECONDARY")));
        events.clear(); state.accept(report(0x4e), 7200); state.accept(report(0), 7340);
        check(events.equals(Arrays.asList("down PRIMARY", "up PRIMARY")));
        events.clear(); state.accept(report(0x6e), 7400); state.accept(report(0), 7500);
        check(events.equals(Arrays.asList("down SQUEEZE", "up SQUEEZE")));
        events.clear(); state.accept(report(0x4b), 7600); state.clear(); state.held(8000);
        check(events.equals(Arrays.asList("down SECONDARY")));
        state.accept(report(0), 8100); check(events.size() == 1);
        events.clear(); state.accept(report(0x4e), 8200); state.setSideButtonLongPress(true);
        events.clear(); state.held(8600); check(events.isEmpty());
        state.accept(report(0x4e), 8700); check(events.isEmpty());
        state.held(9079); check(events.isEmpty());
        state.held(9080); check(events.equals(Arrays.asList("down PRIMARY")));
        System.out.println("PASS pen_button_checks=" + checks);
    }
}
