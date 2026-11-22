# 构建 Xiaomi Pad 6S Pro（sheng）

## 环境

先拉齐 Android 17 ROM 源码及其 Qualcomm CAF / SELinux 公共依赖，使用 Linux 或 WSL
原生文件系统。当前验收基线为 PixelOS seventeen；精确提交见 `patches/rom-manifest.xml`。
安装 ROM 所需主机依赖及 Python 3.11+、Git LFS、rsync、ccache、make、gcc、flex、bison、
bc、cpio、kmod、jq、zstd、libssl-dev、libelf-dev、zlib1g-dev。

## 拉取设备源码

在 ROM 源码根目录执行：

```sh
git lfs install
git clone -b seventeen https://github.com/peiyuesheng666/android_device_xiaomi_sheng.git device/xiaomi/sheng
git clone -b seventeen https://github.com/peiyuesheng666/android_vendor_xiaomi_sheng.git vendor/xiaomi/sheng
git clone -b main https://github.com/peiyuesheng666/android_kernel_xiaomi_sheng_618.git kernel/xiaomi/sheng-build
git -C device/xiaomi/sheng lfs pull
git -C vendor/xiaomi/sheng lfs pull
```

`hardware/xiaomi` 是公共依赖，未随设备仓库重复携带。若 ROM 尚未同步它：

```sh
git clone -b lineage-24.0 https://github.com/LineageOS/android_hardware_xiaomi.git hardware/xiaomi
git -C hardware/xiaomi checkout c3de4412ad6317b820c8cef7c5e80b7cceb4acda
```

同时确保 `hardware/qcom-caf/common`、SM8550 CAF、`device/qcom/sepolicy_vndr`、
`vendor/qcom/opensource` 及 `tools/extract-utils` 等 ROM 公共依赖已同步。
不需要独立的 5.15 内核和旧模块仓库。

## 内核工具链

固定版本及下载仓库见内核项目 `provenance/toolchains.json`，主机构建步骤见
`docs/BUILD.zh-CN.md`。准备以下布局，elfutils 0.193 启用 zstd：

```text
/path/to/kernel-deps/
├── prebuilts/
│   ├── clang/host/linux-x86/clang-r584948c/
│   ├── rust-toolchain/linux-x86/1.91.1.p3/
│   ├── clang-tools/linux-x86/
│   ├── kernel-build-tools/linux_musl-x86/
│   └── build-tools/linux-x86/
└── elfutils-0.193/{include,lib}/
```

## 准备构建

```sh
python3.11 device/xiaomi/sheng/tools/prepare_sheng_rom.py --rom "$PWD" --kernel-deps /path/to/kernel-deps --check
python3.11 device/xiaomi/sheng/tools/prepare_sheng_rom.py --rom "$PWD" --kernel-deps /path/to/kernel-deps
```

脚本验证依赖、LFS 人脸输入和补丁基线，应用 `patches/` 下三组必要 ROM 补丁，
将本仓库 `prebuilts/` 的 DTB/DTBO 放到 `device/xiaomi/sheng-kernel`，建立内核入口
`kernel/xiaomi/sheng -> sheng-build/sources/k618/ws/common`，并建立构建所需的
`../diagnostics/kernel618-android-deps` 工具链链接。它不会刷机或修改 Git 历史。
补丁基线不匹配时停止，需先适配补丁，不能直接忽略。

## 编译

PixelOS：

```sh
export OUT_DIR=out-sheng-pixelos
export USE_CCACHE=1 CCACHE_EXEC=/usr/bin/ccache
source build/envsetup.sh
lunch custom_sheng-cp2a-userdebug
python3 device/xiaomi/sheng/tools/prepare_sheng_desktop_shell.py --rom "$PWD"
python3 device/xiaomi/sheng/tools/prepare_sheng_desktop_settings.py --rom "$PWD"
SHENG_LUNCH=custom_sheng-cp2a-userdebug SHENG_BUILD_JOBS=4 \
    bash device/xiaomi/sheng/tools/build_hardware.sh --full
```

LineageOS 保留 `lineage_sheng-cp2a-userdebug` 产品入口，使用独立源码和输出目录。
公共补丁可能需要适配；当前 PixelOS 的整包/实机验收不能代替 LineageOS 验收。

完整 OTA 包及 boot、init_boot、vendor_boot、recovery 位于
`$OUT_DIR/target/product/sheng/`。内核及外置驱动由正常 ROM 构建规则编译。


## 2026-11-23 发布状态

2026-11-22 完整构建成功；随后按原构建图定向编译传感器 HAL 和配件应用，
重建 vendor、product、vbmeta_system、vbmeta，AVB 链校验通过并刷入实机。
用户已确认四方向旋转和键盘开关配色均正常。完整发布包由这套镜像生成。
不修改 persist 或传感器校准；原厂备份保持只读。
USB、Magisk、KernelSU 保留此前已验收版本，不重复测试。
保留原生 pstore，debug 保留启动 rawdump 日志；无自定义 pystore 节点或自动重启超时。
DP 采用最高可用刷新率优先、同刷新率选最大分辨率的已验收策略；
不宣称任意分辨率切换绿色画面的底层问题已根治。手写笔掌拒仍待优化。
公共仓库版本见 patches/rom-manifest.xml；设备专属修复保留在设备树及内核树。
