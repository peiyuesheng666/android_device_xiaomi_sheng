# pystore：rawdump 内核日志只读导出

内置于 `CONFIG_SHENG_BOOTLOG=y` 的内核，不依赖应用、KSU 模块或挂载
pstore 文件系统。接口位于 procfs，**不替代或占用 `/sys/fs/pstore`**。

```
/proc/pystore/console-rawdump-0
/proc/pystore/console-rawdump-1
```

两个条目分别对应 rawdump 分区 288～298 MiB 中两个 5 MiB 槽（单份含头尾最多 5 MiB）。
读出的内容是原始内核日志文本，不含二进制头尾；可以直接保存为 `.txt`。
槽号不是启动编号，也不保证槽 1 永远更新。两份都导出，按日志内的
`run`、revision 和时间戳区分来源，不能把旧日志当作本次故障记录。

## 使用

需 root 和 `CAP_SYSLOG`，同时受 SELinux 约束；不为普通应用开放权限。
Android 已授权 root 的 Shell 可读取：

```sh
adb exec-out su -c 'cat /proc/pystore/console-rawdump-0'
adb exec-out su -c 'cat /proc/pystore/console-rawdump-1'
```

Recovery 的 root ADB 可直接用 `adb pull` 导出对应节点。
节点只有读取权限，没有写入、清空、删除记录、重启或修改定时器的接口。

每次打开固定读取一个槽，检查分区名称/大小、格式版本、长度边界、
4 KiB 对齐、尾部序号及正文 CRC，然后保留本次打开的稳定副本。
多次分段读取不会混入后续快照；读取不会触发保存，也不会清除磁盘记录。
最多允许四个同时打开的导出文件，缓冲区共最多 20 MiB，关闭即释放。

- 空槽或无记录标记：`ENODATA`。
- 记录损坏、版本不支持：`EBADMSG`，不输出未经验证的正文。
- rawdump 尚未枚举或大小不符：`ENODEV`。
- 短读或磁盘 I/O 失败：`EIO` 或底层错误。

## 写日志与自动重启相互独立

正常记录使用 `sheng_bootlog.enable=1 sheng_bootlog.test_timeout=0`。
保全失败现场的 Recovery 仍应使用 `sheng_bootlog.enable=0`；即使写入器
关闭，pystore 读取节点仍注册，不会为读取而启动写入器。

本次只增加读取节点，没有添加 180 秒或其他自动重启，也没有调整原有
写入周期。release 构建配置保留内置日志；配套镜像命令行和打包流程仍需
分别核对，不能仅凭 `CONFIG_SHENG_BOOTLOG=y` 宣称实机已启用。

## 验证边界

`tools/test_sheng_pystore.py` 编译生产记录校验函数，测试正常、空槽、
长度损坏、正文 CRC、尾部序号、最大正文以及 preserve 模式节点注册顺序。
内核对象可独立定向编译。上述均不等于完整内核链接、AVB 校验、节点权限
验收或实机断电后的日志保留验证。

## 启动阶段限定与 5 MiB 格式

新记录使用版本 2，两个读取节点同步使用 5 MiB 槽；只输出有效正文，不补零。
版本 1 的 1 MiB 记录仍可导出；槽 1 仅在新位置无记录标记时尝试旧偏移，
不会用旧记录掩盖新记录校验失败。新写入可能覆盖旧布局，应先导出旧日志。

设备 init 在 `sys.boot_completed=1` 写入内核 `boot_complete` 单向停止节点：
完成最后一次快照后停止写入，后续故障和重启钩子也不能追加日常日志。
读取节点始终保留。停止节点不能通过写 0 重新开启；Recovery preserve 模式
不启动写入。配套 init 与 SELinux 规则必须一同部署；尚未实机验证。

## 正式版离线打包模式

`package_source_boot_family.py --release-pystore` 与 `--diagnostic-kernel` 互斥。
正式版要求非诊断、已链接的 logger 和 boot-only pystore 审计；旧诊断审计
不能替代，新审计生成与完整链接尚待完成，不能手工补字段伪造通过。
boot 显式 enable=1，Recovery enable=0；两者 test_timeout=0，并去除
旧 pre_driver_hold_ms 和 boot_complete 参数。模块、父镜像与 AVB 检查保留。
此工具不包含 vendor init/SELinux 系统集成；其成功不代表可部署或实机通过。
