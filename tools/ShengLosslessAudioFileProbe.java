// SPDX-License-Identifier: Apache-2.0
import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.os.SystemClock;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.security.MessageDigest;

/** Decode a local file and compare its PCM digest with an independent decoder. */
public final class ShengLosslessAudioFileProbe {
    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalStateException(message);
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) result.append(String.format("%02x", value & 255));
        return result.toString();
    }

    /** Diagnostic only: separates the decoder's raw stream contract from extraction. */
    private static final class ApeStream implements AutoCloseable {
        final RandomAccessFile file;
        final MediaFormat format;
        long remaining;
        long[] frames;
        long firstFrame;
        int frameIndex;

        ApeStream(String path, boolean framed) throws Exception {
            file = new RandomAccessFile(path, "r");
            try {
                byte[] bytes = new byte[52];
                file.readFully(bytes);
                ByteBuffer descriptor = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
                require(descriptor.getInt(0) == 0x2043414d, "Not an APE file");
                int version = descriptor.getShort(4) & 65535;
                require(version >= 3980 && version <= 3990, "Diagnostic needs the modern APE header");
                long descriptorBytes = descriptor.getInt(8) & 0xffffffffL;
                long headerBytes = descriptor.getInt(12) & 0xffffffffL;
                long seekBytes = descriptor.getInt(16) & 0xffffffffL;
                long waveBytes = descriptor.getInt(20) & 0xffffffffL;
                remaining = descriptor.getInt(24) & 0xffffffffL;
                require(descriptor.getInt(28) == 0 && descriptorBytes >= 52 && headerBytes >= 24,
                        "Invalid diagnostic descriptor");
                long start = descriptorBytes + headerBytes + seekBytes + waveBytes;
                require(start <= file.length() && remaining > 0 && remaining <= file.length() - start,
                        "Truncated APE audio");
                file.seek(descriptorBytes);
                bytes = new byte[24];
                file.readFully(bytes);
                ByteBuffer header = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
                int bits = header.getShort(16) & 65535;
                int channels = header.getShort(18) & 65535;
                int rate = header.getInt(20);
                require(bits == 16 && channels >= 1 && channels <= 2 && rate >= 8000 && rate <= 192000,
                        "Diagnostic needs mono/stereo 16-bit PCM");
                require(header.getInt(4) > 0 && header.getInt(8) > 0 && header.getInt(12) > 0,
                        "Invalid APE frame counts");
                ByteBuffer csd = ByteBuffer.allocate(32).order(ByteOrder.LITTLE_ENDIAN);
                csd.putShort((short) version).putShort(header.getShort(0));
                csd.putInt(header.getShort(2) & 65535);
                csd.putInt(header.getInt(4)).putInt(header.getInt(8)).putInt(header.getInt(12));
                csd.putShort((short) bits).putShort((short) channels).putInt(rate).putInt(framed ? 1 : 0).flip();
                format = MediaFormat.createAudioFormat("audio/x-ape", rate, channels);
                format.setByteBuffer("csd-0", csd);
                format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 65536);
                format.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
                if (framed) {
                    int count = header.getInt(12);
                    require(count <= 65536 && seekBytes >= count * 4L, "Invalid diagnostic seek table");
                    frames = new long[count + 1];
                    file.seek(descriptorBytes + headerBytes);
                    for (int index = 0; index < count; index++) {
                        frames[index] = Integer.reverseBytes(file.readInt()) & 0xffffffffL;
                        require(frames[index] >= start && frames[index] < start + remaining
                                && (index == 0 || frames[index] > frames[index - 1]), "Invalid frame offset");
                    }
                    frames[count] = start + remaining;
                    firstFrame = frames[0];
                    require(firstFrame == start, "Unexpected first APE frame");
                    int largest = 0;
                    for (int index = 0; index < count; index++) {
                        long size = frames[index + 1] - frames[index] + ((frames[index] - firstFrame) & 3);
                        size &= ~3L;
                        require(size > 0 && size <= 2 * 1024 * 1024, "Oversized diagnostic frame");
                        largest = Math.max(largest, (int) size + 12);
                    }
                    format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, largest);
                }
                file.seek(start);
            } catch (Throwable error) {
                try { file.close(); } catch (Exception closeError) { error.addSuppressed(closeError); }
                throw error;
            }
        }

        int read(ByteBuffer target) throws Exception {
            if (frames != null) {
                if (frameIndex == frames.length - 1) return -1;
                int skip = (int) ((frames[frameIndex] - firstFrame) & 3);
                long offset = frames[frameIndex] - skip;
                // QTI consumes whole words and reads the next frame prefix at
                // that boundary. Do not duplicate a partial word in two frames.
                int size = (int) ((frames[frameIndex + 1] - offset) & ~3L);
                require(size + 12 <= target.remaining(), "Codec input cannot contain a complete APE frame");
                byte[] data = new byte[size];
                file.seek(offset);
                file.readFully(data);
                target.order(ByteOrder.LITTLE_ENDIAN).putInt(size).putInt(skip).putInt(frameIndex);
                target.put(data);
                frameIndex++;
                return size + 12;
            }
            if (remaining == 0) return -1;
            int size = (int) Math.min(remaining, Math.min(65536, target.remaining()));
            require(size > 0, "Empty codec input buffer");
            byte[] bytes = new byte[size];
            file.readFully(bytes);
            target.put(bytes);
            remaining -= size;
            return size;
        }

        @Override public void close() throws Exception { file.close(); }
    }

    private static void decode(String[] args) throws Exception {
        require(args.length >= 6, "Usage: codec file sample-rate channels pcm-bytes pcm-sha256 [options]");
        boolean apeByteStream = false, apeFrames = false, defaultDecoder = false;
        long seekUs = -1;
        for (int i = 6; i < args.length; i++) {
            if (args[i].equals("--ape-byte-stream")) apeByteStream = true;
            else if (args[i].equals("--ape-frame-stream")) apeFrames = true;
            else if (args[i].equals("--default-decoder")) defaultDecoder = true;
            else if (args[i].startsWith("--seek-us=")) {
                seekUs = Long.parseLong(args[i].substring("--seek-us=".length()));
                require(seekUs >= 0, "Seek time must be nonnegative");
            } else throw new IllegalArgumentException("Unknown option: " + args[i]);
        }
        boolean apeDirect = apeByteStream || apeFrames;
        require(!(apeByteStream && apeFrames), "Only one raw APE diagnostic mode may be selected");
        require(!apeDirect || (!defaultDecoder && seekUs < 0), "Default selection and seeking require MediaExtractor");
        require(!apeDirect || args[0].startsWith("c2.qti.ape."), "APE diagnostic codec required");
        int rate = Integer.parseInt(args[2]), channels = Integer.parseInt(args[3]);
        long expectedBytes = Long.parseLong(args[4]);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        MessageDigest prefixDigest = MessageDigest.getInstance("SHA-256");
        MediaExtractor extractor = new MediaExtractor();
        ApeStream stream = null;
        MediaCodec codec = null;
        boolean started = false;
        Throwable pending = null;
        try {
            MediaFormat format = null;
            if (apeDirect) {
                stream = new ApeStream(args[1], apeFrames);
                format = stream.format;
            } else {
                extractor.setDataSource(args[1]);
                for (int index = 0; index < extractor.getTrackCount(); index++) {
                    MediaFormat candidate = extractor.getTrackFormat(index);
                    if (candidate.getString(MediaFormat.KEY_MIME).startsWith("audio/")) {
                        format = candidate;
                        extractor.selectTrack(index);
                        break;
                    }
                }
            }
            require(format != null, "No audio track exposed by MediaExtractor");
            require(format.getInteger(MediaFormat.KEY_SAMPLE_RATE) == rate
                    && format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) == channels,
                    "Extractor format differs from the reference");
            System.out.println("AUDIO_FILE_INPUT extractor_used=" + !apeDirect + " format=" + format);
            if (seekUs >= 0) {
                extractor.seekTo(seekUs, MediaExtractor.SEEK_TO_PREVIOUS_SYNC);
                System.out.println("AUDIO_FILE_SEEK requested_us=" + seekUs + " actual_us=" + extractor.getSampleTime());
            }
            codec = defaultDecoder ? MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME))
                    : MediaCodec.createByCodecName(args[0]);
            System.out.println("AUDIO_FILE_CODEC actual=" + codec.getName() + " automatic=" + defaultDecoder);
            require(codec.getName().equals(args[0]), "Default decoder differs from expected component");
            codec.configure(format, null, null, 0);
            codec.start();
            started = true;
            boolean inputEos = false, outputEos = false;
            long totalBytes = 0, packets = 0;
            long deadline = SystemClock.elapsedRealtime() + 25000;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputEos && SystemClock.elapsedRealtime() < deadline) {
                if (!inputEos) {
                    int index = codec.dequeueInputBuffer(1000);
                    if (index >= 0) {
                        ByteBuffer input = codec.getInputBuffer(index);
                        input.clear();
                        int size = stream == null ? extractor.readSampleData(input, 0) : stream.read(input);
                        if (size < 0) {
                            codec.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inputEos = true;
                        } else {
                            boolean finalFrame = apeFrames && stream.frameIndex == stream.frames.length - 1;
                            codec.queueInputBuffer(index, 0, size, stream == null ? extractor.getSampleTime() : 0,
                                    finalFrame ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0);
                            inputEos = finalFrame;
                            packets++;
                            if (stream == null) extractor.advance();
                        }
                    }
                }
                int index = codec.dequeueOutputBuffer(info, 1000);
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat output = codec.getOutputFormat();
                    require(output.getInteger(MediaFormat.KEY_SAMPLE_RATE) == rate
                            && output.getInteger(MediaFormat.KEY_CHANNEL_COUNT) == channels,
                            "Decoder changed rate or channels");
                    require(!output.containsKey(MediaFormat.KEY_PCM_ENCODING)
                            || output.getInteger(MediaFormat.KEY_PCM_ENCODING) == AudioFormat.ENCODING_PCM_16BIT,
                            "Reference requires 16-bit PCM");
                    System.out.println("AUDIO_FILE_OUTPUT format=" + output);
                } else if (index >= 0) {
                    try {
                        if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                            ByteBuffer data = codec.getOutputBuffer(index).duplicate();
                            data.position(info.offset).limit(info.offset + info.size);
                            if (totalBytes < expectedBytes) {
                                ByteBuffer prefix = data.duplicate();
                                prefix.limit(prefix.position() + (int) Math.min(prefix.remaining(), expectedBytes - totalBytes));
                                prefixDigest.update(prefix);
                            }
                            digest.update(data);
                            totalBytes += info.size;
                            require(totalBytes <= expectedBytes + 1024 * 1024,
                                    "Decoded PCM exceeds reference length by more than one MiB: " + totalBytes);
                        }
                        outputEos = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    } finally {
                        codec.releaseOutputBuffer(index, false);
                    }
                }
            }
            require(inputEos && outputEos, "Decoder did not complete the stream");
            String actual = hex(digest.digest());
            System.out.println("AUDIO_FILE_LENGTH bytes=" + totalBytes + " expected=" + expectedBytes
                    + " reference_prefix_sha256=" + hex(prefixDigest.digest()));
            require(totalBytes == expectedBytes && actual.equals(args[5]),
                    "PCM differs from reference: bytes=" + totalBytes + " sha256=" + actual);
            System.out.println("AUDIO_FILE_REFERENCE passed=true codec=" + args[0]
                    + " bytes=" + totalBytes + " sha256=" + actual + " packets=" + packets
                    + " extractor_used=" + !apeDirect + " microphone_used=false playback_used=false");
        } catch (Throwable error) {
            pending = error;
            throw error;
        } finally {
            Exception cleanup = null;
            if (codec != null) {
                try { if (started) codec.stop(); } catch (RuntimeException error) { cleanup = error; }
                try { codec.release(); } catch (RuntimeException error) {
                    if (cleanup == null) cleanup = error; else cleanup.addSuppressed(error);
                }
            }
            try { extractor.release(); } catch (RuntimeException error) {
                if (cleanup == null) cleanup = error; else cleanup.addSuppressed(error);
            }
            if (stream != null) {
                try { stream.close(); } catch (Exception error) {
                    if (cleanup == null) cleanup = error; else cleanup.addSuppressed(error);
                }
            }
            if (cleanup != null) {
                if (pending != null) pending.addSuppressed(cleanup); else throw cleanup;
            }
        }
    }

    public static void main(String[] args) {
        try { decode(args); }
        catch (Exception error) {
            System.err.println("AUDIO_FILE_REFERENCE passed=false error=" + error);
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
