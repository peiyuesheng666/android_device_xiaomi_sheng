import java.util.Arrays;
import java.util.Collections;
import org.lineageos.sheng.transition.EmbeddedLaunchPolicy;
import org.lineageos.sheng.transition.EmbeddedLaunchPolicy.Change;

public final class EmbeddedLaunchPolicyTest {
    private static boolean run(String device, String remote, int type, Change... changes) {
        return EmbeddedLaunchPolicy.shouldWait(device, remote, type, 1, 6, Arrays.asList(changes));
    }
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) {
        Change pane = new Change(1, true, false);
        Change root = new Change(6, false, true);
        check(run("sheng", "QuickstepLaunch", 1, pane, root));
        check(!run("other", "QuickstepLaunch", 1, pane, root));
        check(!run("sheng", "OtherRemote", 1, pane, root));
        check(!run("sheng", "QuickstepLaunch", 2, pane, root));
        check(!run("sheng", "QuickstepLaunch", 1, pane, new Change(1, false, true)));
        check(!run("sheng", "QuickstepLaunch", 1, pane, new Change(2, true, true)));
        check(!run("sheng", "QuickstepLaunch", 1, pane, new Change(6, false, false)));
        check(!run("sheng", "QuickstepLaunch", 1, root));
        check(!run("sheng", "QuickstepLaunch", 1));
        System.out.println("9 transition policy cases passed");
    }
}
