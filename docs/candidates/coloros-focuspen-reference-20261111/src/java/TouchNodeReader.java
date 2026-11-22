package com.codex.focuspen;

import java.io.FileReader;
import java.io.IOException;
import java.io.Reader;

/** Small proc/sysfs values. Read to EOF so the NVT driver's global EOF flag clears. */
final class TouchNodeReader {
    interface Source { Reader open() throws IOException; }

    static String read(String path) {
        try { return read(() -> new FileReader(path)); }
        catch (IOException | SecurityException e) { return null; }
    }

    static String read(Source source) throws IOException {
        for (int attempt = 0; attempt < 2; attempt++) {
            StringBuilder value = new StringBuilder();
            try (Reader reader = source.open()) {
                char[] buffer = new char[256];
                int count;
                while ((count = reader.read(buffer)) != -1) {
                    if (count == 0) throw new IOException("zero-length node read");
                    if (value.length() + count > 4096) throw new IOException("node too large");
                    value.append(buffer, 0, count);
                }
            }
            String result = value.toString().replace("\u0000", "").trim();
            if (!result.isEmpty()) return result;
        }
        return null;
    }

    static int stylusState(String value) {
        if ("stylus_enable: 1".equals(value) || "1".equals(value)) return 1;
        if ("stylus_enable: 0".equals(value) || "0".equals(value)) return 0;
        return -1;
    }
}
