# elfuse HVF/ELF 执行层基线报告（第2轮复审完结版）

## 1. 实验环境与上游固化

- **宿主环境**: Apple Silicon ARM64, macOS 27.0.1, Xcode Clang, Hypervisor.framework 支持 (`sysctl -n kern.hv_support` = 1)。
- **实验根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`
- **上游仓库**: [https://github.com/sysprog21/elfuse](https://github.com/sysprog21/elfuse)
- **独立检出目录**: `/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse`
- **固化提交 HEAD**: `8612033dab8dc60728f604a4ea0441895fc16d39`
  - 日期: Mon Oct 12 07:04:25 2026 +0800
  - 主题: Merge pull request #416 from henrybear327/oci/shell
  - 仓库状态: 独立 clone，工作区 clean，未修改任何源码，未触发 commit/push。

---

## 2. 工具链依赖与局部解决方案

### 2.1 依赖分析
- 宿主现有工具：Clang (`/usr/bin/clang`), Make (`/usr/bin/make`), Python3 (`/usr/bin/python3`), Codesign (`/usr/bin/codesign`)。
- 宿主已有局部工具：LLVM 21/22 (`/opt/homebrew/opt/llvm@22`), LLD 21 (`/opt/homebrew/opt/lld@21`)。
- 缺失工具：PATH 中无 `objcopy` / `ninja`，且严格遵守禁止全局 `brew install` 规则。

### 2.2 局部 `tools/elfuse/bin/objcopy` 实现与算法核验
- **定位与作用**: 针对 `elfuse` 构建中 `shim.S -> shim.o (Mach-O) -> shim.bin (raw binary)` 编写专用包装器，路径为 `/Users/mewcapoo/Projects/proton-macos-lab/tools/elfuse/bin/objcopy`。
- **算法细节**:
  1. 仅针对 `objcopy -O binary <in> <out>` 且输入为 Mach-O 64 位文件时激活提取。
  2. 严格校验 Mach-O 头部魔数 (`0xfeedfacf` / `0xcffaedfe`) 与加载命令 `LC_SEGMENT_64`。
  3. 遍历 Section 寻找 `__text`，校验其偏移与大小未越界，直接提取原始平坦二进制（byte-exact）。
  4. 对非 Mach-O 或标准 ELF 操作，透明回退至 `/opt/homebrew/opt/llvm@22/bin/llvm-objcopy`。
  5. 负面用例防护：输入损坏或缺少 `__text` 时显式报错退出（非零退出码），绝不静默输出垃圾数据。
- **独立对齐证据**（详见 `logs/elfuse/objcopy_verification.log`）：
  - `otool -l sources/elfuse/build/shim.o` 确认：`__text` 偏移 = 312 (`0x138`)，大小 = 7516 (`0x1d5c`)。
  - `tools/elfuse/bin/objcopy` 提取文件大小 = 7516。
  - 与 `dd if=shim.o skip=312 count=7516` 字节级比对结果：`cmp` 完全一致（byte-for-byte exact match）。

---

## 3. elfuse 构建与签名产物

- **编译命令**:
  ```bash
  export PATH="/Users/mewcapoo/Projects/proton-macos-lab/tools/elfuse/bin:$PATH"
  make OBJCOPY=/Users/mewcapoo/Projects/proton-macos-lab/tools/elfuse/bin/objcopy elfuse
  ```
- **产物绝对路径**: `/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse/build/elfuse`
- **签名与 Entitlements**:
  - `codesign -v` 验证有效。
  - Entitlements 包含：
    ```xml
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>com.apple.security.hypervisor</key>
        <true/>
    </dict>
    </plist>
    ```
- **基本用法**:
  ```bash
  /Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse/build/elfuse [--verbose] [--timeout N] [--sysroot PATH] <elf-binary> [args...]
  ```

---

## 4. 实测 Fixture 运行与严格验收证据（响应第 2 轮复审）

针对 Lead 第 2 轮复审意见，测试套件 `scripts/elfuse/run_all_baseline.sh` 实现了以下工程规范：
1. **纯 Lab 内存储与完整证据保留**:
   - 彻底移出 `/tmp`，每次运行在 `logs/elfuse/run.XXXXXX` 建立专属执行目录。
   - 每个 fixture 的完整未截断 stdout/stderr 分别持久化于 `logs/elfuse/run.XXXXXX/test_<N>.stdout`，**直接保留不删**，供独立审查。
2. **防覆盖与零软链接规范**:
   - 移除所有 `ln -sf` 覆盖逻辑，每次运行生成唯一的专属日志与证据目录。
   - 参数 `--log <path>` 严格校验：路径必须位于 lab 根目录下；如果指定的目标文件已存在，立即报错并以退出码 2 拒绝覆盖。缺少参数时显式非零退出。
3. **精准耗时与底层退出码校验**:
   - 临时文件捕获避免管道 `head` 引发 `SIGPIPE` 掩盖真实返回码。
   - 逐项显式比对实际退出码与预期退出码（C ELF 预期 42，正向 0，负向 1）。
4. **支持注入伪二进制的负向自我验证**:
   - 支持 `ELFUSE_BIN` 环境变量覆盖。
   - 编写 `scripts/elfuse/test_fake_binary_rejection.sh` 注入故意的错误程序（`tools/elfuse/bin/fake_elfuse`，模拟返回 99），实测 suite 能准确检测到全部用例失败，并返回整体非零退出码（`exit 1`）。

### 测试矩阵与实测结果

| 测试编号 | 测试用例 | 路径 / 命令 | 语义与断言 | 预期 RC | 实测 RC | 耗时 | 状态 |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **TEST 1** | **Assembly hello** | `fixtures/elfuse/hello` | 纯汇编 `write(1, msg, 6)` + `exit(0)`，匹配 `^hello$` | 0 | 0 | 0.036s | **PASS** |
| **TEST 2** | **Freestanding C** | `fixtures/elfuse/test_freestanding` | 独立编译 C ELF，匹配 `Freestanding C ELF on HVF`，退出码 42 | 42 | 42 | 0.031s | **PASS** |
| **TEST 3** | **mmap + JIT** | `fixtures/elfuse/test_mmap_jit` | `mmap` 动态写 AArch64 指令，`mprotect` 改 RX 执行，匹配 `mmap+JIT success: computed 77` | 0 | 0 | 0.028s | **PASS** |
| **TEST 4** | **clone / fork** | `fixtures/elfuse/test_fork` | `clone(SIGCHLD)` 创建子进程，`wait4` 回收，匹配 `Parent reaped child exit code 10` | 0 | 0 | 0.035s | **PASS** |
| **TEST 5** | **glibc ld.so** | `ld-linux-aarch64.so.1` | Debian 2.36 prebuilt dynamic linker 自执行，匹配 `Usage: .*ld-linux-aarch64\.so\.1` | 0 | 0 | 0.028s | **PASS** |
| **TEST 6** | **Negative: 缺失文件** | `/nonexistent_file_for_test` | 不存在文件应拒绝执行，匹配 `cannot read.*No such file` | 1 | 1 | 0.020s | **PASS** |
| **TEST 7** | **Negative: 截断文件** | `fixtures/elfuse/corrupted.elf` | 损坏 ELF 头应显式拒绝，匹配 `failed to read ELF header` | 1 | 1 | 0.020s | **PASS** |

测试套件整体返回码: `0`（全部 7 项用例通过）。  
测试产物保留路径示例: `logs/elfuse/run.9CAvma/`（含 `suite.log` 及 `test_1.stdout` 至 `test_7.stdout`）。

---

## 5. 进阶语义覆盖状态说明 (Verified vs Not-Run)

根据 Team Lead 指令及上游 Proton 原版包匿名拉取受阻（No subscription）的现状，本轮收敛交付基线，各语义模块状态如下：

1. **基础指令与系统调用 (Basic I/O & Lifecycle)**:
   - `write`, `exit`, `exit_group`: **Verified (PASS)**
2. **动态内存与执行权限 (Memory & JIT)**:
   - `mmap` (MAP_PRIVATE \| MAP_ANONYMOUS): **Verified (PASS)**
   - `mprotect` (PROT_READ \| PROT_EXEC 动态权限切换): **Verified (PASS)**
   - JIT 指令缓存一致性与执行: **Verified (PASS)**
3. **多进程支持 (Process Lifecycle)**:
   - `clone` (进程级克隆): **Verified (PASS)**
   - `wait4` (状态回收): **Verified (PASS)**
4. **动态链接库 (Dynamic Linker / glibc)**:
   - 动态链接器直接加载执行 (`ld-linux-aarch64.so.1`): **Verified (PASS)**
   - 完整跨用户态动态 glibc 二进制解析与跨模块符号绑定: **Not-Run**（本轮收敛，避免扩大测试范围）
5. **复杂系统级语义 (SysV IPC / Futex Contention / POSIX Signal)**:
   - 多线程同步 (`futex` 竞争网络)、信号掩码/异步交付、SysV/POSIX 共享内存跨进程管道: **Not-Run**（已固化在 elfuse 自带单元测试库中，后续轮次按需单独调测）
6. **Proton / Wine / FEX 运行**:
   - **Not-Run**（上游 Proton 原版包由于 Steam 匿名鉴权受阻未落地，本轮确认跳过）

---

## 6. 清理与一键复现

- **边界合规**:
  - 所有写入严格限制在 `sources/elfuse`, `tools/elfuse`, `fixtures/elfuse`, `scripts/elfuse`, `logs/elfuse`, `reports/elfuse-baseline.md`。
  - 未动用其他队员工作目录，未触发全局 git commit/push，未修改全局系统与 Steam 配置。
- **一键复现命令**:
  ```bash
  cd /Users/mewcapoo/Projects/proton-macos-lab
  ./scripts/elfuse/run_all_baseline.sh
  ```
- **负例伪程序注入验证**:
  ```bash
  cd /Users/mewcapoo/Projects/proton-macos-lab
  ./scripts/elfuse/test_fake_binary_rejection.sh
  ```
