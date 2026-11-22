// SPDX-License-Identifier: Apache-2.0
import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.os.SystemClock;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.List;

/** Process generated PCM through the installed codec services without recording or playback. */
public final class ShengAudioCodec2RoundTrip {
    private static final int RATE = 48000, CHANNELS = 2, FRAMES = 48000;
    private static final long TIMEOUT_MS = 20000;

    private static final class Packet {
        byte[] data;
        long pts;
        int flags;
        Packet(byte[] data, long pts, int flags) {
            this.data = data;
            this.pts = pts;
            this.flags = flags;
        }
    }

    private static final class Encoded {
        MediaFormat format;
        final List<Packet> packets = new ArrayList<>();
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalStateException(message);
    }

    private static short sample(int frame, int channel) {
        double t = (double) frame / RATE;
        double envelope = 0.55 + 0.35 * Math.sin(2 * Math.PI * 2.3 * t);
        double value = Math.sin(2 * Math.PI * (channel == 0 ? 440 : 613) * t)
                + 0.35 * Math.sin(2 * Math.PI * (channel == 0 ? 997 : 1471) * t);
        return (short) Math.round(14000 * envelope * value);
    }

    private static void release(MediaCodec codec, boolean started, Throwable pending) {
        RuntimeException failure = null;
        try {
            if (started) codec.stop();
        } catch (RuntimeException error) {
            failure = error;
        }
        try {
            codec.release();
        } catch (RuntimeException error) {
            if (failure == null) failure = error;
            else failure.addSuppressed(error);
        }
        if (failure != null) {
            if (pending != null) pending.addSuppressed(failure);
            else throw failure;
        }
    }

    private static Encoded encode(String name, String mime) throws Exception {
        MediaCodec codec = MediaCodec.createByCodecName(name);
        boolean started = false;
        Encoded encoded = new Encoded();
        Throwable pending = null;
        try {
            MediaFormat format = MediaFormat.createAudioFormat(mime, RATE, CHANNELS);
            format.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
            format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 4096 * CHANNELS * 2);
            if (mime.equals(MediaFormat.MIMETYPE_AUDIO_AAC)) {
                format.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC);
                format.setInteger(MediaFormat.KEY_BIT_RATE, 192000);
            } else {
                format.setInteger(MediaFormat.KEY_FLAC_COMPRESSION_LEVEL, 5);
            }
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            codec.start();
            started = true;
            int inputFrames = 0;
            boolean queuedEos = false, outputEos = false;
            long lastPts = Long.MIN_VALUE, deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputEos && SystemClock.elapsedRealtime() < deadline) {
                if (!queuedEos) {
                    int index = codec.dequeueInputBuffer(1000);
                    if (index >= 0) {
                        ByteBuffer buffer = codec.getInputBuffer(index).order(ByteOrder.LITTLE_ENDIAN);
                        buffer.clear();
                        int count = Math.min(FRAMES - inputFrames,
                                Math.min(4096, buffer.remaining() / (CHANNELS * 2)));
                        require(count > 0 || inputFrames == FRAMES, "Encoder input buffer is too small");
                        for (int frame = 0; frame < count; frame++) {
                            for (int channel = 0; channel < CHANNELS; channel++) {
                                buffer.putShort(sample(inputFrames + frame, channel));
                            }
                        }
                        int flags = count == 0 ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0;
                        codec.queueInputBuffer(index, 0, count * CHANNELS * 2,
                                inputFrames * 1000000L / RATE, flags);
                        inputFrames += count;
                        queuedEos = count == 0;
                    }
                }
                int index = codec.dequeueOutputBuffer(info, 1000);
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    encoded.format = codec.getOutputFormat();
                } else if (index >= 0) {
                    if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        require(info.presentationTimeUs >= lastPts, "Encoded timestamps moved backwards");
                        lastPts = info.presentationTimeUs;
                        ByteBuffer buffer = codec.getOutputBuffer(index);
                        buffer.position(info.offset).limit(info.offset + info.size);
                        byte[] bytes = new byte[info.size];
                        buffer.get(bytes);
                        encoded.packets.add(new Packet(bytes, info.presentationTimeUs,
                                info.flags & ~MediaCodec.BUFFER_FLAG_END_OF_STREAM));
                    }
                    outputEos = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    codec.releaseOutputBuffer(index, false);
                }
            }
            require(outputEos && queuedEos && inputFrames == FRAMES, "Encoder did not finish the PCM stream");
            require(encoded.format != null && encoded.packets.size() > 1, "Encoder produced no stream");
            System.out.println("AUDIO_ENCODE codec=" + name + " frames=" + inputFrames
                    + " packets=" + encoded.packets.size() + " eos=true format=" + encoded.format);
            return encoded;
        } catch (Exception | Error error) {
            pending = error;
            throw error;
        } finally {
            release(codec, started, pending);
        }
    }

    private static short[] decode(String name, Encoded encoded) throws Exception {
        MediaCodec codec = MediaCodec.createByCodecName(name);
        boolean started = false;
        ByteArrayOutputStream pcm = new ByteArrayOutputStream();
        Throwable pending = null;
        try {
            codec.configure(encoded.format, null, null, 0);
            codec.start();
            started = true;
            int packet = 0;
            boolean queuedEos = false, outputEos = false, checkedFormat = false;
            long lastPts = Long.MIN_VALUE, deadline = SystemClock.elapsedRealtime() + TIMEOUT_MS;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputEos && SystemClock.elapsedRealtime() < deadline) {
                if (!queuedEos) {
                    int index = codec.dequeueInputBuffer(1000);
                    if (index >= 0) {
                        if (packet == encoded.packets.size()) {
                            codec.queueInputBuffer(index, 0, 0, FRAMES * 1000000L / RATE,
                                    MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            queuedEos = true;
                        } else {
                            Packet item = encoded.packets.get(packet++);
                            ByteBuffer buffer = codec.getInputBuffer(index);
                            buffer.clear();
                            require(buffer.remaining() >= item.data.length, "Decoder packet does not fit");
                            buffer.put(item.data);
                            codec.queueInputBuffer(index, 0, item.data.length, item.pts, item.flags);
                        }
                    }
                }
                int index = codec.dequeueOutputBuffer(info, 1000);
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat format = codec.getOutputFormat();
                    require(format.getInteger(MediaFormat.KEY_SAMPLE_RATE) == RATE, "Incorrect decoded sample rate");
                    require(format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) == CHANNELS, "Incorrect decoded channels");
                    require(!format.containsKey(MediaFormat.KEY_PCM_ENCODING)
                            || format.getInteger(MediaFormat.KEY_PCM_ENCODING) == AudioFormat.ENCODING_PCM_16BIT,
                            "Unexpected decoded PCM format");
                    checkedFormat = true;
                } else if (index >= 0) {
                    if (info.size > 0) {
                        require(info.presentationTimeUs >= lastPts, "Decoded timestamps moved backwards");
                        lastPts = info.presentationTimeUs;
                        ByteBuffer buffer = codec.getOutputBuffer(index);
                        buffer.position(info.offset).limit(info.offset + info.size);
                        byte[] bytes = new byte[info.size];
                        buffer.get(bytes);
                        pcm.write(bytes);
                        require(pcm.size() < (FRAMES + 8192) * CHANNELS * 2, "Excess decoded PCM");
                    }
                    outputEos = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    codec.releaseOutputBuffer(index, false);
                }
            }
            require(outputEos && queuedEos && checkedFormat, "Decoder did not finish the stream");
            require(pcm.size() % (CHANNELS * 2) == 0, "Partial PCM frame");
            short[] samples = new short[pcm.size() / 2];
            ByteBuffer.wrap(pcm.toByteArray()).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(samples);
            require(samples.length / CHANNELS >= FRAMES - 4096, "Decoded PCM is truncated");
            System.out.println("AUDIO_DECODE codec=" + name + " frames=" + samples.length / CHANNELS + " eos=true");
            return samples;
        } catch (Exception | Error error) {
            pending = error;
            throw error;
        } finally {
            release(codec, started, pending);
        }
    }

    private static Encoded extract(String path) throws Exception {
        MediaExtractor extractor = new MediaExtractor();
        try {
            extractor.setDataSource(path);
            Encoded encoded = new Encoded();
            for (int track = 0; track < extractor.getTrackCount(); track++) {
                MediaFormat format = extractor.getTrackFormat(track);
                String mime = format.getString(MediaFormat.KEY_MIME);
                if (mime != null && mime.startsWith("audio/")) {
                    encoded.format = format;
                    extractor.selectTrack(track);
                    break;
                }
            }
            require(encoded.format != null, "No audio track in generated fixture");
            require(encoded.format.getInteger(MediaFormat.KEY_SAMPLE_RATE) == RATE,
                    "Fixture has an unexpected sample rate");
            require(encoded.format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) == CHANNELS,
                    "Fixture has an unexpected channel count");
            encoded.format.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
            ByteBuffer buffer = ByteBuffer.allocate(2 * 1024 * 1024);
            int largest = 0;
            while (true) {
                buffer.clear();
                int size = extractor.readSampleData(buffer, 0);
                if (size < 0) break;
                require(size > 0 && size <= buffer.capacity(), "Invalid extracted packet size");
                require((extractor.getSampleFlags() & MediaExtractor.SAMPLE_FLAG_ENCRYPTED) == 0,
                        "Generated audio fixture must be unencrypted");
                buffer.position(0).limit(size);
                byte[] bytes = new byte[size];
                buffer.get(bytes);
                encoded.packets.add(new Packet(bytes, extractor.getSampleTime(), 0));
                largest = Math.max(largest, size);
                require(encoded.packets.size() < 10000, "Fixture has too many packets");
                if (!extractor.advance()) break;
            }
            require(!encoded.packets.isEmpty(), "Extractor produced no compressed audio");
            encoded.format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, largest);
            System.out.println("AUDIO_EXTRACT packets=" + encoded.packets.size()
                    + " format=" + encoded.format);
            return encoded;
        } finally {
            extractor.release();
        }
    }

    private static void check(short[] decoded, boolean lossless) {
        int outputFrames = decoded.length / CHANNELS;
        if (lossless) {
            require(outputFrames == FRAMES, "Lossless decoder changed the sample count");
            for (int frame = 0; frame < FRAMES; frame++) {
                for (int channel = 0; channel < CHANNELS; channel++) {
                    require(decoded[frame * CHANNELS + channel] == sample(frame, channel),
                            "Lossless content mismatch at " + frame + ":" + channel);
                }
            }
            System.out.println("AUDIO_CONTENT lossless=true exact_samples=" + decoded.length);
            return;
        }
        // AAC may preserve priming/padding. Find a shared frame offset, then
        // check both channels against the generated waveform at every sample.
        double best = Double.POSITIVE_INFINITY;
        int bestOffset = 0;
        for (int offset = -4096; offset <= 4096; offset++) {
            double error = 0;
            int count = 0;
            for (int frame = 4096; frame < FRAMES - 4096; frame += 32) {
                int out = frame + offset;
                if (out < 0 || out >= outputFrames) continue;
                for (int channel = 0; channel < CHANNELS; channel++) {
                    double delta = decoded[out * CHANNELS + channel] - sample(frame, channel);
                    error += delta * delta;
                    count++;
                }
            }
            if (count > 0 && error / count < best) {
                best = error / count;
                bestOffset = offset;
            }
        }
        double error = 0, energy = 0;
        int count = 0;
        for (int frame = 4096; frame < FRAMES - 4096; frame++) {
            int out = frame + bestOffset;
            require(out >= 0 && out < outputFrames, "AAC alignment truncated the stream");
            for (int channel = 0; channel < CHANNELS; channel++) {
                double expected = sample(frame, channel);
                double delta = decoded[out * CHANNELS + channel] - expected;
                error += delta * delta;
                energy += expected * expected;
                count++;
            }
        }
        double relativeError = Math.sqrt(error / energy);
        require(relativeError < 0.12, "AAC content mismatch: relative RMS error=" + relativeError);
        System.out.println("AUDIO_CONTENT lossless=false offset=" + bestOffset
                + " relative_rms_error=" + relativeError + " compared_samples=" + count);
    }

    public static void main(String[] args) {
        try {
            if (args.length != 0) {
                boolean nativeConfig = args[0].equals("--file-alac-native-config");
                require(args.length == 3 && (args[0].equals("--file") || nativeConfig),
                        "Usage: --file codec generated-audio-file");
                Encoded encoded = extract(args[2]);
                if (nativeConfig) {
                    require("audio/alac".equals(encoded.format.getString(MediaFormat.KEY_MIME)),
                            "Native configuration diagnostic requires ALAC");
                    ByteBuffer network = encoded.format.getByteBuffer("csd-0").duplicate();
                    require(network.remaining() == 24, "Unexpected ALAC configuration size");
                    byte[] bytes = new byte[24];
                    network.get(bytes);
                    network = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN);
                    ByteBuffer nativeBytes = ByteBuffer.wrap(bytes.clone()).order(ByteOrder.LITTLE_ENDIAN);
                    for (int offset : new int[] {0, 12, 16, 20}) {
                        nativeBytes.putInt(offset, network.getInt(offset));
                    }
                    nativeBytes.putShort(10, network.getShort(10));
                    encoded.format.setByteBuffer("csd-0", nativeBytes);
                    System.out.println("AUDIO_CONFIG diagnostic_override=alac_little_endian");
                }
                check(decode(args[1], encoded), true);
                System.out.println("AUDIO_FILE_DECODE passed=true codec=" + args[1]
                        + " native_config_override=" + nativeConfig
                        + " microphone_used=false playback_used=false");
                return;
            }
            Encoded aac = encode("c2.qti.aac.hw.encoder", MediaFormat.MIMETYPE_AUDIO_AAC);
            check(decode("c2.qti.aac.hw.decoder", aac), false);
            Encoded flac = encode("c2.android.flac.encoder", MediaFormat.MIMETYPE_AUDIO_FLAC);
            check(decode("c2.qti.flac.sw.decoder", flac), true);
            System.out.println("AUDIO_ROUNDTRIP passed=true microphone_used=false playback_used=false");
        } catch (Exception error) {
            System.err.println("AUDIO_ROUNDTRIP passed=false error=" + error);
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
