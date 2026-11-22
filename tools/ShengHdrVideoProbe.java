// SPDX-License-Identifier: Apache-2.0
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.os.SystemClock;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import org.json.JSONArray;
import org.json.JSONObject;

/** Compare locally generated Main10 frames without using a display surface. */
public final class ShengHdrVideoProbe {
    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalStateException(message);
    }

    private static String hex(byte[] data) {
        StringBuilder value = new StringBuilder(data.length * 2);
        for (byte item : data) value.append(String.format("%02x", item & 255));
        return value.toString();
    }

    private static String staticInfo(MediaFormat format) {
        if (!format.containsKey(MediaFormat.KEY_HDR_STATIC_INFO)) return "";
        ByteBuffer info = format.getByteBuffer(MediaFormat.KEY_HDR_STATIC_INFO).duplicate();
        byte[] data = new byte[info.remaining()];
        info.get(data);
        return hex(data);
    }

    private static JSONObject colors(MediaFormat format) throws Exception {
        JSONObject values = new JSONObject();
        for (String name : new String[]{MediaFormat.KEY_COLOR_STANDARD, MediaFormat.KEY_COLOR_RANGE,
                MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.KEY_COLOR_FORMAT}) {
            if (format.containsKey(name)) values.put(name, format.getInteger(name));
        }
        return values.put("hdr_static_info", staticInfo(format));
    }

    private static void checkColors(MediaFormat format, JSONObject reference) throws Exception {
        for (String name : new String[]{MediaFormat.KEY_COLOR_STANDARD, MediaFormat.KEY_COLOR_RANGE,
                MediaFormat.KEY_COLOR_TRANSFER}) {
            require(format.containsKey(name) && format.getInteger(name) == reference.getInt(name),
                    "Color metadata mismatch for " + name + ": " + colors(format));
        }
        String expected = reference.getString("hdr_static_info"), actual = staticInfo(format);
        // CCodec can expose an empty Type 1 structure for a stream without
        // mastering metadata. HLG does not require HDR10 mastering metadata.
        boolean absent = expected.isEmpty() && (actual.isEmpty() || actual.equals(hex(new byte[25])));
        require(absent || actual.equals(expected), "HDR static metadata mismatch: " + actual);
    }

    private static String frameDigest(Image image, int width, int height) throws Exception {
        require(image != null, "Codec did not provide an output image");
        require(image.getFormat() == ImageFormat.YCBCR_P010,
                "Expected P010 output, got image format " + image.getFormat());
        Rect crop = image.getCropRect();
        require(crop.width() == width && crop.height() == height, "Unexpected output crop: " + crop);
        Image.Plane[] planes = image.getPlanes();
        require(planes.length == 3, "P010 output must expose three component planes");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        for (int p = 0; p < planes.length; p++) {
            int divisor = p == 0 ? 1 : 2;
            int rows = height / divisor, columns = width / divisor;
            ByteBuffer data = planes[p].getBuffer().duplicate().order(ByteOrder.LITTLE_ENDIAN);
            int rowStride = planes[p].getRowStride(), pixelStride = planes[p].getPixelStride();
            require(pixelStride >= 2 && rowStride >= columns * pixelStride, "Invalid P010 strides");
            int base = data.position() + crop.top / divisor * rowStride + crop.left / divisor * pixelStride;
            byte[] row = new byte[columns * 2];
            for (int y = 0; y < rows; y++) {
                for (int x = 0; x < columns; x++) {
                    int offset = base + y * rowStride + x * pixelStride;
                    require(offset >= 0 && offset + 2 <= data.limit(), "Truncated P010 plane");
                    int value = data.getShort(offset) & 65535;
                    require((value & 63) == 0, "P010 sample has nonzero padding bits");
                    value >>>= 6;
                    row[x * 2] = (byte) value;
                    row[x * 2 + 1] = (byte) (value >>> 8);
                }
                digest.update(row);
            }
        }
        return hex(digest.digest());
    }

    private static JSONObject decode(String path, JSONObject reference) throws Exception {
        int width = reference.getInt("width"), height = reference.getInt("height");
        JSONArray expected = reference.getJSONArray("frames");
        MediaExtractor extractor = new MediaExtractor();
        MediaCodec codec = null;
        boolean started = false;
        Throwable pending = null;
        try {
            extractor.setDataSource(path);
            MediaFormat input = null;
            for (int track = 0; track < extractor.getTrackCount(); track++) {
                MediaFormat format = extractor.getTrackFormat(track);
                if ("video/hevc".equals(format.getString(MediaFormat.KEY_MIME))) {
                    require(input == null, "Multiple HEVC tracks");
                    input = format;
                    extractor.selectTrack(track);
                }
            }
            require(input != null && input.getInteger(MediaFormat.KEY_WIDTH) == width
                    && input.getInteger(MediaFormat.KEY_HEIGHT) == height, "Unexpected extracted format");
            JSONObject result = new JSONObject().put("input_colors", colors(input));
            input.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUVP010);
            codec = MediaCodec.createDecoderByType("video/hevc");
            require(codec.getName().equals("c2.qti.hevc.decoder"), "Unexpected decoder: " + codec.getName());
            result.put("decoder", codec.getName()).put("default_decoder_selection", true);
            codec.configure(input, null, null, 0);
            codec.start();
            started = true;
            boolean inputEos = false, outputEos = false;
            int queued = 0, received = 0;
            JSONArray frames = new JSONArray();
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            long deadline = SystemClock.elapsedRealtime() + 20000;
            while (!outputEos) {
                require(SystemClock.elapsedRealtime() < deadline, "Main10 decoding timed out");
                if (!inputEos) {
                    int index = codec.dequeueInputBuffer(10000);
                    if (index >= 0) {
                        ByteBuffer data = codec.getInputBuffer(index);
                        data.clear();
                        int size = extractor.readSampleData(data, 0);
                        if (size < 0) {
                            codec.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inputEos = true;
                        } else {
                            require(queued < expected.length(), "More compressed samples than reference frames");
                            codec.queueInputBuffer(index, 0, size, extractor.getSampleTime(), 0);
                            queued++;
                            extractor.advance();
                        }
                    }
                }
                int index = codec.dequeueOutputBuffer(info, 10000);
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    result.put("output_colors", colors(codec.getOutputFormat()));
                } else if (index >= 0) {
                    try {
                        if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                            require(received < expected.length(), "Unexpected extra decoded frame");
                            JSONObject wanted = expected.getJSONObject(received);
                            require(Math.abs(info.presentationTimeUs - wanted.getLong("pts_us")) <= 2,
                                    "Output timestamp mismatch at frame " + received);
                            MediaFormat output = codec.getOutputFormat(index);
                            result.put("output_colors", colors(output));
                            checkColors(output, reference);
                            Image image = codec.getOutputImage(index);
                            String digest;
                            try { digest = frameDigest(image, width, height); }
                            finally { if (image != null) image.close(); }
                            require(digest.equals(wanted.getString("sha256")),
                                    "Decoded P010 differs from FFmpeg at frame " + received + ": " + digest);
                            frames.put(new JSONObject().put("pts_us", info.presentationTimeUs).put("sha256", digest));
                            received++;
                        }
                        outputEos = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    } finally { codec.releaseOutputBuffer(index, false); }
                }
            }
            require(queued == expected.length() && received == expected.length(), "Incomplete Main10 stream");
            return result.put("frames", frames).put("eos", true).put("content_exact", true)
                    .put("metadata_checked", true).put("display_surface_used", false);
        } catch (Throwable error) {
            pending = error;
            throw error;
        } finally {
            try {
                if (codec != null) {
                    try { if (started) codec.stop(); }
                    finally { codec.release(); }
                }
            } catch (Throwable error) {
                if (pending != null) pending.addSuppressed(error);
                else throw error;
            } finally { extractor.release(); }
        }
    }

    public static void main(String[] args) throws Exception {
        try {
            require(args.length == 2, "Usage: clip.mp4 reference.json");
            JSONObject reference = new JSONObject(new String(Files.readAllBytes(Paths.get(args[1])),
                    StandardCharsets.UTF_8));
            System.out.println("HDR_VIDEO " + decode(args[0], reference).put("passed", true));
        } catch (Exception error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
