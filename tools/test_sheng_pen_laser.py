import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from sheng_pen_shortcut_fixtures import shortcut_fixtures


parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
source = Path(__file__).resolve().parents[1] / 'interfaces/input/stylus'
java = Path(os.environ.get('SHENG_ROM_ROOT', '/root/sheng-pixelos/android')) / 'prebuilts/jdk/jdk21/linux-x86/bin'
args.output.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix='laser-', dir=args.output))
fixtures = {
    'android/content/Context.java': 'package android.content; public class Context {}',
    'android/util/DisplayMetrics.java': 'package android.util; public class DisplayMetrics {public float density=2;public int widthPixels=2000,heightPixels=1000;}',
    'android/content/res/Resources.java': '''package android.content.res;
public class Resources {public android.util.DisplayMetrics getDisplayMetrics(){return new android.util.DisplayMetrics();}}''',
    'android/util/Log.java': '''package android.util;
public class Log {public static final java.util.List<String> messages=new java.util.ArrayList<>();
public static int i(String tag,String message){messages.add(message);return 0;}
public static int w(String tag,String message){messages.add(message);return 0;}}''',
    'android/graphics/Paint.java': '''package android.graphics;
public class Paint {public static final int ANTI_ALIAS_FLAG=1;public int color;
public Paint(int flags){} public void setColor(int value){color=value;}}''',
    'android/graphics/Canvas.java': '''package android.graphics;
public class Canvas {public static class Circle {public final float x,y,radius;public final int color;
Circle(float x,float y,float radius,int color){this.x=x;this.y=y;this.radius=radius;this.color=color;}}
public final java.util.List<Circle> circles=new java.util.ArrayList<>();
public void drawCircle(float x,float y,float radius,Paint paint){circles.add(new Circle(x,y,radius,paint.color));}}''',
    'android/view/View.java': '''package android.view;
public class View {public int width,height,originX,originY,invalidations;
public View(android.content.Context context){} protected void onDraw(android.graphics.Canvas canvas){}
public void getLocationOnScreen(int[] origin){origin[0]=originX;origin[1]=originY;}
public int getWidth(){return width;}public int getHeight(){return height;}
public android.content.res.Resources getResources(){return new android.content.res.Resources();}
public void postInvalidateOnAnimation(){invalidations++;}}''',
}
fixtures.update(shortcut_fixtures)
for name, contents in fixtures.items():
    path = work / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
actual = [source / 'app/org/lineageos/sheng/stylus/PenLaserView.java',
          source / 'app/org/lineageos/sheng/stylus/PenShortcutController.java',
          source / 'app/org/lineageos/sheng/stylus/PenAppRouting.java',
          source / 'src/org/lineageos/sheng/stylus/PenButtonState.java',
          source / 'src/org/lineageos/sheng/stylus/PenModel.java',
          source / 'app/org/lineageos/sheng/stylus/PenInputIdentity.java',
          source.parent / 'pen/common/org/lineageos/sheng/pen/controls/PenControls.java',
          source.parent / 'pen/common/org/lineageos/sheng/pen/controls/PenAppOverrides.java',
          source.parent / 'pen/common/org/lineageos/sheng/pen/controls/PenMenuEntry.java',
          source / 'tests/PenLaserViewTest.java', source / 'tests/PenShortcutControllerTest.java']
framework = java.parents[4] / ('out-clean-ota-20261116/soong/.intermediates/frameworks/base/'
                             'framework-minus-apex/android_common/combined/framework.jar')
classpath = os.pathsep.join(map(str, [work / 'classes', framework]))
receipt = {'passed': False, 'hardware_tested': False, 'android_compositor_tested': False,
           'canvas': 'recording_double',
           'android_service_doubles': True, 'menu_and_screenshot_boundaries_doubled': True,
           'framework_sha256': hashlib.sha256(framework.read_bytes()).hexdigest(),
           'fixture_sha256': hashlib.sha256(Path(__file__).with_name('sheng_pen_shortcut_fixtures.py').read_bytes()).hexdigest(),
           'source_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in actual}}
try:
    result = subprocess.run([str(java / 'javac'), '-encoding', 'UTF-8', '-cp', str(framework), '-d', str(work / 'classes'),
                             *map(str, work.rglob('*.java')), *map(str, actual)],
                            text=True, capture_output=True, timeout=60)
    receipt['compile_output'] = result.stdout + result.stderr
    result.check_returncode()
    result = subprocess.run([str(java / 'java'), '-cp', classpath,
                             'org.lineageos.sheng.stylus.PenLaserViewTest'],
                            text=True, capture_output=True, timeout=60)
    receipt['stdout'] = result.stdout
    receipt['stderr'] = result.stderr
    result.check_returncode()
    result = subprocess.run([str(java / 'java'), '-cp', classpath,
                             'org.lineageos.sheng.stylus.PenShortcutControllerTest'],
                            text=True, capture_output=True, timeout=60)
    receipt['controller_stdout'] = result.stdout
    receipt['controller_stderr'] = result.stderr
    result.check_returncode()
    receipt['passed'] = True
finally:
    (args.output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
