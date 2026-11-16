// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import java.util.ArrayList;
import java.util.List;

public final class KeyboardFeatureCommandsTest {
    private static int checks;
    private static void check(boolean value) { ++checks; if (!value) throw new AssertionError("check " + checks); }
    private static final class Queue implements KeyboardFeatureCommands.Scheduler {
        final List<Runnable> tasks = new ArrayList<>();
        @Override public void postDelayed(Runnable task, long delay) { check(delay == 50); tasks.add(task); }
        @Override public void remove(Runnable task) { tasks.remove(task); }
        void run() { List<Runnable> batch = new ArrayList<>(tasks); tasks.clear(); for (Runnable task:batch) task.run(); }
    }
    public static void main(String[] args) {
        Queue queue = new Queue();
        List<String> sent = new ArrayList<>();
        boolean[] usable = {true}, transport = {true};
        KeyboardFeatureCommands features = new KeyboardFeatureCommands(queue,
                (command, enabled) -> { if (!transport[0]) return false; sent.add(command+":"+enabled); return true; },
                () -> usable[0]);
        check(features.send(0x21,true));
        check(sent.size()==1);
        features.acknowledge(0x21,0); queue.run();
        check(sent.size()==2); queue.run(); check(sent.size()==2);
        features.send(0x21,true); features.acknowledge(0x21,1); queue.run(); check(sent.size()==3);
        features.send(0x21,true); Runnable old=queue.tasks.get(0);
        features.send(0x21,false); old.run(); check(sent.size()==5);
        queue.run(); check(sent.size()==6 && sent.get(5).equals("33:false"));
        features.send(0x21,true); features.clear(); queue.run(); check(sent.size()==7);
        features.send(0x21,true); usable[0]=false; queue.run(); check(sent.size()==8);
        check(!features.send(0x21,true));
        usable[0]=true; transport[0]=false;
        check(!features.send(0x21,true) && queue.tasks.isEmpty());
        System.out.println("PASS " + checks + " keyboard feature checks");
    }
}
