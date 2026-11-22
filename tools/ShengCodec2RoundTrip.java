// SPDX-License-Identifier: Apache-2.0
import android.graphics.Rect;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCrypto;
import android.media.MediaDrm;
import android.media.MediaFormat;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Base64;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.json.JSONArray;
import org.json.JSONObject;

/** Encode generated YUV frames and decode them through the installed hardware services. */
public final class ShengCodec2RoundTrip {
    private static final int WIDTH = 128, HEIGHT = 128, FRAMES = 8;
    private static final long TIMEOUT_MS = 15000;

    private static final class Packet {
        final byte[] bytes;
        final long pts;
        final int flags;
        Packet(byte[] bytes, long pts, int flags) {
            this.bytes = bytes;
            this.pts = pts;
            this.flags = flags;
        }
    }

    private static final class Encoded {
        MediaFormat format;
        final List<Packet> packets = new ArrayList<>();
    }

    private static final class ClearKeySession implements AutoCloseable {
        private static final UUID SCHEME = UUID.fromString("e2719d58-a985-b3c9-781a-b030af78d30e");
        // Public, generated fixture material; never taken from a device license.
        final byte[] keyId = new byte[16];
        final byte[] key = new byte[16];
        MediaDrm engine;
        byte[] session;
        MediaCrypto crypto;

        private static String base64(byte[] value) {
            return Base64.encodeToString(value, Base64.URL_SAFE | Base64.NO_PADDING | Base64.NO_WRAP);
        }

        ClearKeySession() throws Exception {
            for (int i = 0; i < 16; i++) {
                keyId[i] = (byte) (i + 1);
                key[i] = (byte) (0x71 + i);
            }
            engine = new MediaDrm(SCHEME);
            try {
                session = engine.openSession();
                UUID common = UUID.fromString("1077efec-c0b2-4d02-ace3-3c1e52e2fb4b");
                ByteBuffer pssh = ByteBuffer.allocate(52);
                pssh.putInt(52).putInt(0x70737368).putInt(0x01000000)
                        .putLong(common.getMostSignificantBits()).putLong(common.getLeastSignificantBits())
                        .putInt(1).put(keyId).putInt(0);
                MediaDrm.KeyRequest request = engine.getKeyRequest(session, pssh.array(), "video/mp4",
                        MediaDrm.KEY_TYPE_STREAMING, null);
                JSONObject requested = new JSONObject(new String(request.getData(), StandardCharsets.UTF_8));
                JSONArray kids = requested.getJSONArray("kids");
                require(kids.length() == 1 && kids.getString(0).equals(base64(keyId)), "Unexpected ClearKey request");
                JSONObject response = new JSONObject().put("type", "temporary").put("keys", new JSONArray()
                        .put(new JSONObject().put("kty", "oct").put("kid", base64(keyId)).put("k", base64(key))));
                engine.provideKeyResponse(session, response.toString().getBytes(StandardCharsets.UTF_8));
                crypto = new MediaCrypto(SCHEME, session);
                require(!crypto.requiresSecureDecoderComponent("video/avc"), "ClearKey fixture needs readable output");
            } catch (Throwable error) {
                try { close(); } catch (Throwable closeError) { error.addSuppressed(closeError); }
                throw error;
            }
        }

        byte[] iv(int packet) {
            return ByteBuffer.allocate(16).putLong(0x3141592653589793L).putLong(packet).array();
        }

        byte[] encrypt(byte[] plain, byte[] iv) throws Exception {
            Cipher cipher = Cipher.getInstance("AES/CTR/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new IvParameterSpec(iv));
            return cipher.doFinal(plain);
        }

        @Override public void close() {
            try {
                if (crypto != null) { crypto.release(); crypto = null; }
            } finally {
                if (engine != null) {
                    try { if (session != null) { engine.closeSession(session); session = null; } }
                    finally { engine.close(); engine = null; }
                }
            }
        }
    }

    private static void require(boolean value, String message) {
        if (!value) throw new IllegalStateException(message);
    }

    private static long pts(int frame) {
        return (frame + 1) * 100000L;
    }

    private static int sample(int frame, int plane, int x, int y) {
        if (plane == 1) return 96;
        if (plane == 2) return 160;
        return 32 + (frame * 11 + (x / 8) * 7 + (y / 8) * 5) % 160;
    }

    private static void fill(Image image, int frame) {
        require(image != null && image.getPlanes().length == 3, "Encoder requires three YUV planes");
        Rect crop = image.getCropRect();
        require(crop.width() == WIDTH && crop.height() == HEIGHT, "Unexpected input crop");
        Image.Plane[] planes = image.getPlanes();
        for (int p = 0; p < planes.length; p++) {
            int div = p == 0 ? 1 : 2;
            ByteBuffer buffer = planes[p].getBuffer();
            int stride = planes[p].getRowStride(), pixel = planes[p].getPixelStride();
            int base = buffer.position() + crop.top / div * stride + crop.left / div * pixel;
            for (int y = 0; y < HEIGHT / div; y++) {
                for (int x = 0; x < WIDTH / div; x++) {
                    int offset = base + y * stride + x * pixel;
                    require(offset < buffer.limit(), "Input plane too short");
                    buffer.put(offset, (byte) sample(frame, p, x, y));
                }
            }
        }
    }

    private static double check(Image image, int frame) {
        require(image != null && image.getPlanes().length == 3, "Decoder did not expose YUV planes");
        Rect crop = image.getCropRect();
        require(crop.width() == WIDTH && crop.height() == HEIGHT, "Unexpected output crop");
        double maximum = 0;
        Image.Plane[] planes = image.getPlanes();
        for (int p = 0; p < planes.length; p++) {
            int div = p == 0 ? 1 : 2;
            ByteBuffer buffer = planes[p].getBuffer();
            int stride = planes[p].getRowStride(), pixel = planes[p].getPixelStride();
            int base = buffer.position() + crop.top / div * stride + crop.left / div * pixel;
            long error = 0;
            for (int y = 0; y < HEIGHT / div; y++) {
                for (int x = 0; x < WIDTH / div; x++) {
                    int offset = base + y * stride + x * pixel;
                    require(offset < buffer.limit(), "Output plane too short");
                    error += Math.abs((buffer.get(offset) & 255) - sample(frame, p, x, y));
                }
            }
            double mean = (double) error / (WIDTH / div * HEIGHT / div);
            require(mean < 12.0, "Decoded content mismatch: frame=" + frame + " plane=" + p + " mae=" + mean);
            maximum = Math.max(maximum, mean);
        }
        return maximum;
    }

    private static void release(MediaCodec codec, boolean started) {
        try {
            if (started) codec.stop();
        } finally {
            codec.release();
        }
    }

    private static Encoded encode(String mime, String name) throws Exception {
        MediaCodec codec = MediaCodec.createByCodecName(name);
        boolean started = false;
        try {
            MediaFormat format = MediaFormat.createVideoFormat(mime, WIDTH, HEIGHT);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT,
                    MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            format.setInteger(MediaFormat.KEY_BIT_RATE, 600000);
            format.setInteger(MediaFormat.KEY_FRAME_RATE, 30);
            format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            codec.start();
            started = true;
            Encoded result = new Encoded();
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            int queued = 0;
            boolean inputEos = false, outputEos = false;
            long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
            while (!outputEos) {
                require(SystemClock.elapsedRealtime() < deadline, "Encoder timed out");
                if (!inputEos) {
                    int index = codec.dequeueInputBuffer(10000);
                    if (index >= 0) {
                        if (queued == FRAMES) {
                            codec.queueInputBuffer(index, 0, 0, pts(FRAMES), MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inputEos = true;
                        } else {
                            fill(codec.getInputImage(index), queued);
                            codec.queueInputBuffer(index, 0, WIDTH * HEIGHT * 3 / 2, pts(queued), 0);
                            queued++;
                        }
                    }
                }
                int index = codec.dequeueOutputBuffer(info, 10000);
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    result.format = codec.getOutputFormat();
                } else if (index >= 0) {
                    if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        ByteBuffer buffer = codec.getOutputBuffer(index).duplicate();
                        buffer.position(info.offset);
                        buffer.limit(info.offset + info.size);
                        byte[] bytes = new byte[info.size];
                        buffer.get(bytes);
                        result.packets.add(new Packet(bytes, info.presentationTimeUs,
                                info.flags & ~MediaCodec.BUFFER_FLAG_END_OF_STREAM));
                    }
                    outputEos = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    codec.releaseOutputBuffer(index, false);
                }
            }
            require(result.format != null && result.packets.size() == FRAMES,
                    "Encoder did not return all frames");
            return result;
        } finally {
            release(codec, started);
        }
    }

    private static void decode(String mime, String name, Encoded encoded, ClearKeySession protectedInput) throws Exception {
        MediaCodec codec = MediaCodec.createByCodecName(name);
        boolean started = false;
        try {
            encoded.format.setInteger(MediaFormat.KEY_COLOR_FORMAT,
                    MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            codec.configure(encoded.format, null, protectedInput == null ? null : protectedInput.crypto, 0);
            codec.start();
            started = true;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            int queued = 0;
            boolean inputEos = false, outputEos = false;
            Set<Long> timestamps = new HashSet<>();
            double maximumError = 0;
            long deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
            while (!outputEos) {
                require(SystemClock.elapsedRealtime() < deadline, "Decoder timed out");
                if (!inputEos) {
                    int index = codec.dequeueInputBuffer(10000);
                    if (index >= 0) {
                        if (queued == encoded.packets.size()) {
                            codec.queueInputBuffer(index, 0, 0, pts(FRAMES), MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inputEos = true;
                        } else {
                            Packet packet = encoded.packets.get(queued++);
                            ByteBuffer buffer = codec.getInputBuffer(index);
                            require(buffer != null, "Missing decoder input");
                            buffer.clear();
                            require(buffer.remaining() >= packet.bytes.length, "Decoder input is too small");
                            if (protectedInput == null) {
                                buffer.put(packet.bytes);
                                codec.queueInputBuffer(index, 0, packet.bytes.length, packet.pts, packet.flags);
                            } else {
                                byte[] iv = protectedInput.iv(queued - 1);
                                byte[] encrypted = protectedInput.encrypt(packet.bytes, iv);
                                require(encrypted.length == packet.bytes.length, "CTR changed packet length");
                                buffer.put(encrypted);
                                MediaCodec.CryptoInfo cryptoInfo = new MediaCodec.CryptoInfo();
                                cryptoInfo.set(1, new int[]{0}, new int[]{encrypted.length}, protectedInput.keyId,
                                        iv, MediaCodec.CRYPTO_MODE_AES_CTR);
                                codec.queueSecureInputBuffer(index, 0, cryptoInfo, packet.pts, packet.flags);
                            }
                        }
                    }
                }
                int index = codec.dequeueOutputBuffer(info, 10000);
                if (index >= 0) {
                    if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        long timestamp = info.presentationTimeUs;
                        int frame = (int) (timestamp / 100000L) - 1;
                        require(frame >= 0 && frame < FRAMES && timestamp == pts(frame),
                                "Output timestamp differs from the generated input");
                        require(timestamps.add(timestamp), "Duplicate decoded frame");
                        maximumError = Math.max(maximumError, check(codec.getOutputImage(index), frame));
                    }
                    outputEos = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    codec.releaseOutputBuffer(index, false);
                }
            }
            require(timestamps.size() == FRAMES, "Decoder dropped frames");
            System.out.println("CODEC_ROUNDTRIP: mime=" + mime + " frames=" + timestamps.size()
                    + " max_plane_mae=" + maximumError + " eos=true content_checked=true"
                    + " encrypted_packets=" + (protectedInput == null ? 0 : queued));
        } finally {
            release(codec, started);
        }
    }

    public static void main(String[] args) throws Exception {
        boolean clearKey = args.length == 1 && args[0].equals("--clearkey");
        require(args.length == 0 || clearKey, "This probe only uses its generated YUV input");
        if (clearKey) {
            if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
            Class.forName("android.app.ActivityThread").getMethod("systemMain").invoke(null);
        }
        try (ClearKeySession protectedInput = clearKey ? new ClearKeySession() : null) {
            for (String type : new String[]{"avc", "hevc"}) {
                String mime = "video/" + type;
                Encoded encoded = encode(mime, "c2.qti." + type + ".encoder");
                decode(mime, "c2.qti." + type + ".decoder", encoded, protectedInput);
            }
        }
        System.out.println("CODEC_ROUNDTRIP: passed=true codecs=4 camera_used=false display_used=false"
                + " clearkey=" + clearKey + " network_used=false");
    }
}
