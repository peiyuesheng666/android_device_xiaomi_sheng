// SPDX-License-Identifier: Apache-2.0
import android.app.ActivityThread;
import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.hardware.SensorDirectChannel;
import android.os.Handler;
import android.os.Looper;
import android.os.MemoryFile;
import android.view.OrientationEventListener;
import android.view.WindowManager;
import java.util.Arrays;
import java.util.HashMap;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Reads the sensor frame used by CameraX and the frame used for display rotation. */
public final class ShengOrientationProbe {
    public static void main(String[] args) {
        Looper.prepareMainLooper();
        Context context = ActivityThread.systemMain().getSystemContext();
        SensorManager manager = context.getSystemService(SensorManager.class);
        Handler handler = new Handler(Looper.getMainLooper());
        HashMap<Integer, Integer> counts = new HashMap<>();
        HashMap<Integer, float[]> latest = new HashMap<>();
        MemoryFile directMemory;
        SensorDirectChannel direct;
        try {
            directMemory = new MemoryFile("sheng-direction-probe", 104 * 256);
            direct = manager.createDirectChannel(directMemory);
            for (int type : new int[]{Sensor.TYPE_ACCELEROMETER,
                    Sensor.TYPE_GYROSCOPE, Sensor.TYPE_MAGNETIC_FIELD}) {
                Sensor sensor = manager.getDefaultSensor(type);
                if (sensor != null && sensor.isDirectChannelTypeSupported(
                        SensorDirectChannel.TYPE_MEMORY_FILE)) {
                    System.out.println("DIRECT_REGISTER type=" + type + " token="
                            + direct.configure(sensor, SensorDirectChannel.RATE_NORMAL));
                }
            }
        } catch (Exception e) {
            System.out.println("DIRECT_ERROR " + e);
            directMemory = null;
            direct = null;
        }
        final MemoryFile memory = directMemory;
        final SensorDirectChannel channel = direct;
        OrientationEventListener orientation = new OrientationEventListener(context) {
            @Override public void onOrientationChanged(int degrees) {
                System.out.println("CAMERAX_ORIENTATION degrees=" + degrees);
            }
        };
        SensorEventListener listener = new SensorEventListener() {
            @Override public void onAccuracyChanged(Sensor sensor, int accuracy) {}
            @Override public void onSensorChanged(SensorEvent event) {
                int type = event.sensor.getType();
                int count = counts.getOrDefault(type, 0) + 1;
                counts.put(type, count);
                latest.put(type, event.values.clone());
                if (count <= 3 || count % 25 == 0) {
                    System.out.println("SENSOR type=" + type + " name=" + event.sensor.getName()
                            + " values=" + Arrays.toString(event.values));
                }
            }
        };
        for (int type : new int[]{Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GRAVITY,
                Sensor.TYPE_DEVICE_ORIENTATION, Sensor.TYPE_ROTATION_VECTOR,
                Sensor.TYPE_GAME_ROTATION_VECTOR, Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR,
                Sensor.TYPE_GYROSCOPE, Sensor.TYPE_MAGNETIC_FIELD,
                Sensor.TYPE_ACCELEROMETER_UNCALIBRATED, Sensor.TYPE_GYROSCOPE_UNCALIBRATED,
                Sensor.TYPE_MAGNETIC_FIELD_UNCALIBRATED}) {
            Sensor sensor = manager.getDefaultSensor(type);
            System.out.println("REGISTER type=" + type + " success=" + (sensor != null
                    && manager.registerListener(listener, sensor, 200000, handler)));
        }
        orientation.enable();
        handler.postDelayed(() -> {
            System.out.println("DISPLAY rotation=" + context.getSystemService(WindowManager.class)
                    .getDefaultDisplay().getRotation());
            orientation.disable();
            manager.unregisterListener(listener);
            if (channel != null) {
                channel.configure(null, SensorDirectChannel.RATE_STOP);
                try {
                    byte[] data = new byte[memory.length()];
                    memory.readBytes(data, 0, 0, data.length);
                    ByteBuffer buffer = ByteBuffer.wrap(data).order(ByteOrder.nativeOrder());
                    HashMap<Integer, double[]> sums = new HashMap<>();
                    for (int offset = 0; offset + 104 <= data.length; offset += 104) {
                        int type = buffer.getInt(offset + 8);
                        if (buffer.getInt(offset) != 104 || buffer.getInt(offset + 12) == 0) continue;
                        double[] sum = sums.computeIfAbsent(type, ignored -> new double[4]);
                        for (int axis = 0; axis < 3; axis++) {
                            sum[axis] += buffer.getFloat(offset + 24 + 4 * axis);
                        }
                        sum[3]++;
                    }
                    for (int type : sums.keySet()) {
                        double[] sum = sums.get(type);
                        System.out.println("DIRECT_AVERAGE type=" + type + " count=" + sum[3]
                                + " xyz=" + Arrays.toString(new double[]{sum[0]/sum[3],
                                sum[1]/sum[3], sum[2]/sum[3]})
                                + " fmq=" + Arrays.toString(latest.get(type)));
                    }
                } catch (Exception e) {
                    System.out.println("DIRECT_READ_ERROR " + e);
                } finally {
                    channel.close();
                    memory.close();
                }
            }
            for (int type : new int[]{Sensor.TYPE_ROTATION_VECTOR,
                    Sensor.TYPE_GAME_ROTATION_VECTOR, Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR}) {
                float[] vector = latest.get(type);
                if (vector == null) continue;
                float[] matrix = new float[9];
                SensorManager.getRotationMatrixFromVector(matrix, vector);
                System.out.println("FUSED_GRAVITY type=" + type + " xyz="
                        + Arrays.toString(new float[]{matrix[6] * SensorManager.GRAVITY_EARTH,
                        matrix[7] * SensorManager.GRAVITY_EARTH,
                        matrix[8] * SensorManager.GRAVITY_EARTH}));
            }
            System.out.println("COMPLETE counts=" + counts);
            System.exit(0);
        }, 6000);
        Looper.loop();
    }
}
