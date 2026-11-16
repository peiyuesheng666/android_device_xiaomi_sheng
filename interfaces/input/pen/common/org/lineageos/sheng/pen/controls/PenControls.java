// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.controls;

/** Device-owned shortcut vocabulary shared by the transport and Settings. */
public final class PenControls {
    private PenControls() {}
    public static final String PREFIX = "sheng_pen_";
    public static final String SENSITIVITY = PREFIX + "squeeze_sensitivity";
    public static final String VIBRATION = PREFIX + "gesture_vibration";
    public static final String MENU = PREFIX + "menu_actions";

    public enum Action {
        NONE("不执行操作", "No action"), MENU("快捷菜单", "Shortcut menu"),
        BACK("返回", "Back"), HOME("主屏幕", "Home"), RECENTS("最近任务", "Recent apps"),
        MEDIA("播放或暂停", "Play or pause"), SCREENSHOT("截屏", "Screenshot"),
        ASSISTANT("语音助理", "Assistant"), SETTINGS("手写笔设置", "Pen settings"),
        UNDO("撤销", "Undo"), REDO("重做", "Redo");
        private final String chinese, english;
        Action(String chinese, String english) { this.chinese = chinese; this.english = english; }
        public String title(boolean zh) { return zh ? chinese : english; }
        public static Action read(String value, Action fallback) {
            if (value != null) for (Action action : values()) if (action.name().equals(value)) return action;
            return fallback;
        }
    }

    public enum Gesture {
        SQUEEZE("握压笔身", "Squeeze", Action.MENU, 1),
        PRIMARY("主按键长按", "Hold primary button", Action.MENU, 0),
        SECONDARY("副按键长按", "Hold secondary button", Action.SCREENSHOT, 0);
        private final String chinese, english;
        public final Action fallback;
        public final int haptic;
        Gesture(String chinese, String english, Action fallback, int haptic) {
            this.chinese = chinese; this.english = english; this.fallback = fallback; this.haptic = haptic;
        }
        public String title(boolean zh) { return zh ? chinese : english; }
        public String key() { return PREFIX + "action_" + name().toLowerCase(java.util.Locale.ROOT); }
        public boolean longPress() { return this == PRIMARY || this == SECONDARY; }
    }

    public static final Action[] DEFAULT_MENU = {Action.BACK, Action.HOME, Action.RECENTS,
            Action.MEDIA, Action.SCREENSHOT, Action.SETTINGS};

    public static Action[] menu(String stored) {
        if (stored == null) return DEFAULT_MENU.clone();
        java.util.ArrayList<Action> result = new java.util.ArrayList<>();
        for (String token : stored.split(",")) {
            Action action = Action.read(token, Action.NONE);
            if (action != Action.NONE && action != Action.MENU && !result.contains(action)) result.add(action);
            if (result.size() == 6) break;
        }
        return result.isEmpty() ? DEFAULT_MENU.clone() : result.toArray(new Action[0]);
    }

    public static int level(String value, int fallback, int maximum) {
        try { int parsed = Integer.parseInt(value); return parsed >= 0 && parsed <= maximum ? parsed : fallback; }
        catch (RuntimeException invalid) { return fallback; }
    }
}
