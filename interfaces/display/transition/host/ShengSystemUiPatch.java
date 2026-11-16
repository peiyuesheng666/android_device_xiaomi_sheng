// SPDX-License-Identifier: Apache-2.0
import com.android.tools.r8.D8;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Set;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

/** Builds from this invocation's SystemUI outputs; never edits a platform source file. */
public final class ShengSystemUiPatch {
    private static final String HANDLER = "com/android/wm/shell/transition/RemoteTransitionHandler.class";
    private static final String BRIDGE = "org/lineageos/sheng/transition/EmbeddedTransitionBridge";
    private static byte[] instrument(byte[] data) {
        ClassWriter writer = new ClassWriter(0);
        int[] patched = {0};
        new ClassReader(data).accept(new ClassVisitor(Opcodes.ASM9, writer) {
            @Override public MethodVisitor visitMethod(int access, String name, String desc,
                    String signature, String[] exceptions) {
                MethodVisitor original = super.visitMethod(access, name, desc, signature, exceptions);
                if (!name.equals("mergeAnimation")) return original;
                String expected = "(Landroid/os/IBinder;Landroid/window/TransitionInfo;"
                        + "Landroid/view/SurfaceControl$Transaction;Landroid/view/SurfaceControl$Transaction;"
                        + "Landroid/os/IBinder;Lcom/android/wm/shell/transition/Transitions$TransitionFinishCallback;)V";
                if (!desc.equals(expected)) throw new IllegalStateException("Unsupported merge ABI: " + desc);
                return new MethodVisitor(Opcodes.ASM9, original) {
                    @Override public void visitMethodInsn(int opcode, String owner, String method,
                            String descriptor, boolean isInterface) {
                        if (owner.equals("android/window/RemoteTransition")
                                && method.equals("getRemoteTransition")) {
                            Label proceed = new Label();
                            // Preserve the already-loaded remote for the original invocation.
                            super.visitInsn(Opcodes.DUP);
                            super.visitVarInsn(Opcodes.ALOAD, 2);
                            super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "shouldWait",
                                    "(Landroid/window/RemoteTransition;Landroid/window/TransitionInfo;)Z", false);
                            super.visitJumpInsn(Opcodes.IFEQ, proceed);
                            super.visitInsn(Opcodes.POP);
                            super.visitInsn(Opcodes.RETURN);
                            super.visitLabel(proceed);
                            super.visitFrame(Opcodes.F_SAME1, 0, null, 1,
                                    new Object[]{"android/window/RemoteTransition"});
                            patched[0]++;
                        }
                        super.visitMethodInsn(opcode, owner, method, descriptor, isInterface);
                    }
                    @Override public void visitMaxs(int stack, int locals) {
                        super.visitMaxs(Math.max(stack, 3), locals);
                    }
                };
            }
        }, 0);
        if (patched[0] != 1) throw new IllegalStateException("Expected one insertion: " + patched[0]);
        return writer.toByteArray();
    }

    private static void write(ZipOutputStream output, String name, byte[] bytes) throws Exception {
        CRC32 crc = new CRC32(); crc.update(bytes);
        ZipEntry entry = new ZipEntry(name);
        entry.setTime(0); entry.setMethod(ZipEntry.STORED);
        entry.setSize(bytes.length); entry.setCrc(crc.getValue());
        output.putNextEntry(entry); output.write(bytes); output.closeEntry();
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 7) throw new IllegalArgumentException(
                "base.apk combined.jar policy.jar sdk.jar framework.jar work-directory output.apk");
        Path work = Path.of(args[5]); Files.createDirectories(work);
        Path combined = work.resolve("combined.jar");
        Set<String> classes = new HashSet<>();
        boolean handlerFound = false;
        try (ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(combined))) {
            for (int index : new int[]{1, 2}) {
                try (ZipFile input = new ZipFile(args[index])) {
                    Enumeration<? extends ZipEntry> entries = input.entries();
                    while (entries.hasMoreElements()) {
                        ZipEntry entry = entries.nextElement();
                        if (!entry.getName().endsWith(".class")) continue;
                        if (!classes.add(entry.getName())) throw new IllegalStateException(
                                "Duplicate class: " + entry.getName());
                        byte[] data = input.getInputStream(entry).readAllBytes();
                        if (entry.getName().equals(HANDLER)) {
                            if (index != 1) throw new IllegalStateException("Handler is not from SystemUI");
                            data = instrument(data); handlerFound = true;
                        }
                        write(output, entry.getName(), data);
                    }
                }
            }
        }
        if (!handlerFound || !classes.contains(BRIDGE + ".class"))
            throw new IllegalStateException("Missing source-built handler or device policy");
        Path dex = work.resolve("dex"); Files.createDirectories(dex);
        D8.main(new String[]{"--release", "--lib", args[3], "--classpath", args[4], "--min-api", "37",
                "--output", dex.toString(), combined.toString()});
        try (ZipFile input = new ZipFile(args[0]);
             ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(Path.of(args[6])))) {
            Enumeration<? extends ZipEntry> entries = input.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                if (entry.getName().matches("classes[0-9]*\\.dex")
                        || entry.getName().startsWith("META-INF/")) continue;
                ZipEntry copy = new ZipEntry(entry);
                if (copy.getMethod() == ZipEntry.DEFLATED) copy.setCompressedSize(-1);
                output.putNextEntry(copy);
                try (InputStream stream = input.getInputStream(entry)) { stream.transferTo(output); }
                output.closeEntry();
            }
            try (var files = Files.list(dex)) {
                for (Path path : files.filter(p -> p.toString().endsWith(".dex")).sorted().toList())
                    write(output, path.getFileName().toString(), Files.readAllBytes(path));
            }
        }
    }
}
