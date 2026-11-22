// SPDX-License-Identifier: Apache-2.0
import android.content.Context;
import android.hardware.display.DisplayManager;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaCrypto;
import android.media.MediaDrm;
import android.os.Looper;
import android.view.Display;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

/** Inspect codec/display capabilities and open then close empty DRM sessions. */
public final class ShengMediaCapabilitiesProbe {
    private static JSONObject drm(String name, UUID uuid) throws Exception {
        JSONObject result = new JSONObject().put("name", name);
        boolean supported = MediaDrm.isCryptoSchemeSupported(uuid);
        result.put("supported", supported);
        if (!supported) return result;
        MediaDrm engine = null;
        byte[] session = null;
        try {
            engine = new MediaDrm(uuid);
            for (String property : new String[]{"vendor", "version", "description", "algorithms", "securityLevel"}) {
                try { result.put(property, engine.getPropertyString(property)); }
                catch (Exception error) { result.put(property + "_error", error.toString()); }
            }
            result.put("avc_hw_secure_all_supported", MediaDrm.isCryptoSchemeSupported(
                    uuid, "video/avc", MediaDrm.SECURITY_LEVEL_HW_SECURE_ALL));
            result.put("max_hdcp_level", engine.getMaxHdcpLevel());
            result.put("connected_hdcp_level", engine.getConnectedHdcpLevel());
            session = engine.openSession();
            result.put("session_opened", true).put("session_security_level", engine.getSecurityLevel(session));
            MediaCrypto crypto = new MediaCrypto(uuid, session);
            try {
                result.put("avc_requires_secure_decoder", crypto.requiresSecureDecoderComponent("video/avc"));
                result.put("hevc_requires_secure_decoder", crypto.requiresSecureDecoderComponent("video/hevc"));
            } finally { crypto.release(); }
        } catch (Exception error) {
            result.put("error", error.toString());
        } finally {
            if (engine != null) {
                try {
                    if (session != null) {
                        engine.closeSession(session);
                        result.put("session_closed", true);
                    }
                } finally { engine.close(); }
            }
        }
        return result;
    }

    public static void main(String[] args) throws Exception {
        // MediaDrm obtains its package attribution from the current Application.
        // app_process does not create one until the system context is attached.
        if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        JSONObject result = new JSONObject();
        JSONArray codecs = new JSONArray();
        for (MediaCodecInfo codec : new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
            if (codec.isEncoder() || codec.isAlias()) continue;
            for (String type : codec.getSupportedTypes()) {
                if (!type.startsWith("video/") && !type.equals("audio/x-ape")) continue;
                MediaCodecInfo.CodecCapabilities caps = codec.getCapabilitiesForType(type);
                JSONArray profiles = new JSONArray();
                for (MediaCodecInfo.CodecProfileLevel profile : caps.profileLevels) {
                    profiles.put(new JSONObject().put("profile", profile.profile).put("level", profile.level));
                }
                codecs.put(new JSONObject().put("name", codec.getName()).put("mime", type)
                        .put("hardware_accelerated", codec.isHardwareAccelerated())
                        .put("software_only", codec.isSoftwareOnly())
                        .put("secure_supported", caps.isFeatureSupported(MediaCodecInfo.CodecCapabilities.FEATURE_SecurePlayback))
                        .put("secure_required", caps.isFeatureRequired(MediaCodecInfo.CodecCapabilities.FEATURE_SecurePlayback))
                        .put("profiles", profiles));
            }
        }
        result.put("codecs", codecs);
        result.put("drm", new JSONArray()
                .put(drm("clearkey", UUID.fromString("e2719d58-a985-b3c9-781a-b030af78d30e")))
                .put(drm("widevine", UUID.fromString("edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"))));
        JSONObject displayInfo = new JSONObject();
        try {
            Display display = context.getSystemService(DisplayManager.class).getDisplay(Display.DEFAULT_DISPLAY);
            Display.HdrCapabilities hdr = display.getHdrCapabilities();
            JSONArray types = new JSONArray();
            for (int type : hdr.getSupportedHdrTypes()) types.put(type);
            displayInfo.put("hdr_types", types).put("max_luminance", hdr.getDesiredMaxLuminance())
                    .put("max_average_luminance", hdr.getDesiredMaxAverageLuminance())
                    .put("min_luminance", hdr.getDesiredMinLuminance())
                    .put("wide_color_gamut", display.isWideColorGamut());
        } catch (Exception error) { displayInfo.put("error", error.toString()); }
        result.put("display", displayInfo).put("license_requested", false).put("network_used", false)
                .put("playback_used", false).put("screenshot_taken", false);
        System.out.println("MEDIA_CAPABILITIES " + result);
    }
}
