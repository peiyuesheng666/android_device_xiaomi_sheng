// SPDX-License-Identifier: Apache-2.0
// Isolated REAL Soong fixtures, not a product build or runtime acceptance.
// Run with the ROM's Go workspace; do not add files to public repositories.
package replacement_test

import (
	"strings"
	"testing"

	"android/soong/android"
	"android/soong/cc"
	"github.com/google/blueprint/proptools"
)

func TestDebugSourceBuiltReplacementAcrossNamespace(t *testing.T) {
	for _, debug := range []bool{false, true} {
		name := "user"
		if debug {
			name = "userdebug"
		}
		t.Run(name, func(t *testing.T) {
			fixture := android.GroupFixturePreparers(
				cc.PrepareForIntegrationTestWithCc,
				// The standard mock toolchain omits ramdisk variants. Supply
				// those fixture variants; the real product already has them.
				android.FixtureModifyMockFS(func(fs android.MockFS) {
					path := cc.DefaultCcCommonTestModulesDir + "Android.bp"
					bp := string(fs[path])
					for _, name := range []string{"toolchain_libs_defaults", "crt_defaults"} {
						needle := `name: "` + name + `",`
						bp = strings.ReplaceAll(bp, needle, needle+"\nramdisk_available: true,")
					}
					fs[path] = []byte(bp)
				}),
				android.PrepareForTestWithAndroidMk,
				android.PrepareForTestWithNamespace,
				// nil means ALL real global neverallow rules, not a relaxed set.
				android.PrepareForTestWithNeverallowRules(nil),
				android.FixtureModifyProductVariables(func(v android.FixtureProductVariables) {
					v.Debuggable = proptools.BoolPtr(debug)
					v.NamespacesToExport = []string{"device/xiaomi/sheng"}
					if debug {
						v.VendorVars = map[string]map[string]string{"sheng": {"first_stage_rootfix": "true"}}
					}
				}),
				android.MockFS{
					"public.cpp":                    nil,
					"device/xiaomi/sheng/owned.cpp": nil,
					"device/xiaomi/sheng/Android.bp": []byte(`
soong_namespace {}
cc_binary {
    name: "sheng_overlay_remounter",
    srcs: ["owned.cpp"],
    installable: false,
    compile_multilib: "64",
    static_executable: true,
    stl: "none",
    system_shared_libs: [],
}
cc_prebuilt_binary {
    name: "overlay_remounter",
    srcs: [":sheng_overlay_remounter"],
    prefer: true,
    enabled: select(soong_config_variable("sheng", "first_stage_rootfix"), {
        "true": true,
        default: false,
    }),
    compile_multilib: "64",
    static_executable: true,
    install_in_xbin: true,
    stl: "none",
    system_shared_libs: [],
    strip: { none: true },
}
cc_binary {
    name: "sheng_init_first_stage",
    srcs: ["owned.cpp"],
    installable: false,
    ramdisk: true,
    compile_multilib: "64",
    static_executable: true,
    stl: "none",
    system_shared_libs: [],
}
cc_prebuilt_binary {
    name: "init_first_stage",
    srcs: [":sheng_init_first_stage"],
    stem: "init",
    prefer: true,
    enabled: select(soong_config_variable("sheng", "first_stage_rootfix"), {
        "true": true,
        default: false,
    }),
    ramdisk: true,
    install_in_root: true,
    compile_multilib: "64",
    static_executable: true,
    stl: "none",
    system_shared_libs: [],
    strip: { none: true },
}
`),
				}.AddToFixture(),
			).RunTestWithBp(t, `
cc_binary {
    name: "overlay_remounter",
    srcs: ["public.cpp"],
    compile_multilib: "64",
    static_executable: true,
    install_in_xbin: true,
    stl: "none",
    system_shared_libs: [],
}
cc_binary {
    name: "init_first_stage",
    stem: "init",
    srcs: ["public.cpp"],
    ramdisk: true,
    install_in_root: true,
    compile_multilib: "64",
    static_executable: true,
    stl: "none",
    system_shared_libs: [],
}
`)
			for _, module := range []struct{ name, variant string }{
				{"overlay_remounter", "android_arm64_armv8-a"},
				{"init_first_stage", "android_ramdisk_arm64_armv8-a"},
			} {
				source := fixture.ModuleForTests(t, module.name, module.variant).Module().(*cc.Module)
				// ReplacedByPrebuilt hides the original from Make; it does not
				// set SkipInstall. Symbol copying explicitly honors this hiding.
				if source.IsReplacedByPrebuilt() != debug || source.IsHideFromMake() != debug {
					t.Fatalf("%s source replaced=%v hidden=%v; want %v", module.name,
						source.IsReplacedByPrebuilt(), source.IsHideFromMake(), debug)
				}
				if debug {
					for _, output := range fixture.ModuleForTests(t, module.name, module.variant).AllOutputs() {
						if strings.Contains(output, "/symbols/") {
							t.Fatalf("replaced %s still produces symbol file %s", module.name, output)
						}
					}
				}
			}
		})
	}
}
