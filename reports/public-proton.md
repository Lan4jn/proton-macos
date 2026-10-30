# 公开 ARM64 Proton 包与 Linux 用户态获取

## 当前证据

已从 DroidDeck 相关组件作者维护的公开 Release 获得原版 Valve 文件的再分发 seed。下载文件的 SHA-256 与固定提交的目录记录及 GitHub Release asset digest 一致。**这验证了下载字节与发布者记录一致，不等于独立验证 Valve 签名或 Steam depot manifest 的全部内容。**

- 目录固定提交：`The412Banner/winlator-contents@05b4c81bce56cb2c76878ee0b76bbcfe250d3356`，`steam-seed.json`。
- Release：`steam-proton-arm64-25502785`。
- 文件：`artifacts/public-proton/proton-experimental-arm64-25502785.tar.zst`。
- 398113534 字节，SHA-256 `d6c480a90d981801be0906a3f3418eb9bd9461c30e411140951cb0daf9d2a189`。
- 发布者声明：App 4427310、Depot 4427311、Build 25502785、Manifest 6971993485335684515。
- 包内 version：`1790245028 experimental-11.0-20260924-arm64`。
- 本地路径/关键文件摘要：`artifacts/public-proton/bundle.json`。
- 原始解压目录：`artifacts/public-proton/extracted/root/.local/share/Steam/steamapps/common/Proton Experimental (ARM64)`。

原有匿名 SteamCMD `No subscription` 仍是真实的历史结果，但已不是本轮继续 Wine 实验的阻断。

## 实际文件审计

`logs/acquisition/real-binary-audit.json` 覆盖真实 Wine、wineserver、ntdll.so、FEX native .so 与 FEX PE DLL。Wine/wineserver/ntdll/FEX .so 为 Linux AArch64 ELF；FEX PE DLL 头报告 AMD64，不能仅凭此字段认定其整个内部 ABI。Wine wrapper 仅需 glibc 2.34，而 ntdll.so 和 wineserver 实际还需要 GLIBC_2.38。旧 glibc 2.36 下失败；lab 内 Debian glibc 2.41 下版本查询成功。修复了审计器原先未被合成样本覆盖的 Elf64_Vernaux 结构格式错误，新增真实格式回归测试。

## 完整 Linux 用户态（不是 Linux OS VM）

另获取 DroidDeck-Components `linuxfs-r9`：790907606 字节，SHA-256 `d3240c1531531615b0dd06b6ad56e92db9015a8641eb18c3a613835ae45992e7`。目录与 Release asset digest 一致，源元数据保留在 `artifacts/public-proton/linuxfs-catalog.json`、`linuxfs-release.json`。直连 GitHub 连接超时后，公开 GitHub Release asset API 下载成功，没有使用凭据。

第一次在 case-insensitive APFS 普通目录解压出现 terminfo 大小写冲突，`tar` 退出1；保留该不完整目录 `fixtures/runtime/arch-root` 和失败日志，不将其视为完整运行环境。随后创建 lab 内 `fixtures/runtime/arch-case.sparsebundle`，挂载到 `fixtures/runtime/arch-case`，case-sensitive APFS 完整解压退出0。设备节点未提取。镜像是文件系统容器，不是运行 Linux 内核的虚拟机。

实际 Linux Python 3.14.7 经 elfuse/HVF 执行，`platform.machine()` 为 `aarch64`，ctypes/fcntl/subprocess 导入通过；见 `logs/runtime/run-8sobzp40`。原始 FEX native 模块以 `ctypes.CDLL(..., mode=2)` 实际装载成功：`logs/runtime/run-njak1o36`。**动态装载成功不是 FEX 已执行 x64 指令的证明。**

## 原件与派生物

原始 Proton 文件与 elfuse 源码保持原样。`fixtures/runtime/proton-derived` 是独立克隆，增加了 `files/bin -> bin-arm64` 以对应 Wine 编译出的 wineserver 搜索目录。前置实验的权限/布局问题均写入日志，不将派生布局称为未改动的原目录。

## 挂载恢复

本轮创建的 APFS 文件系统在实验期间保持挂载，后续可对照 `logs/acquisition/apfs-attach.log` 的镜像和挂载点恢复。只应对实验创建的镜像执行卸载，不涉及系统盘。没有修改真实 Steam 配置、全局包或提交/推送代码。
