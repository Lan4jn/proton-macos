# 完整 Valve Wine 候选源码 win32u v3 真实编译集成与分层验证技术报告

- **任务编号**：task-118
- **执行角色**：wine-guard-verifier (Team Teammate)
- **审查与验证目标**：
  1. 从前序最小 guest 探针推进到完整 Valve Wine 官方 commit 源码环境的真实构建与集成；
  2. 获取并解包完整官方归档包（commit: `dc26e61847081a1b5cb0733dc30feba6ee575482`），保留 pristine 与 patched 双树；
  3. 在实验室隔离环境下打通 Wine 构建依赖链（Host 工具阶 + Target ELF 交叉阶），不进行任何 Homebrew 全局安装；
  4. 验证完整 Wine 规则下 baseline 与 patched 源码目标文件（`vulkan.o`、`d3dkmt.o`）编译与对比；
  5. 成功生成完整的 `aarch64-unix/win32u.so`（包含动态 `R_AARCH64_TLSDESC` 重定位项），恪守不擅自装载至运行态 Wine 的安全红线；
  6. 严格按五层构建梯队（`configure` -> `generated_headers` -> `baseline_objects` -> `patched_objects` -> `linked_so`）实测并如实记录。
- **实验工件根目录**：/Users/mewcapoo/Projects/proton-macos-lab
- **关联工件与物理哈希**：
  - 官方源码归档：`sources/wine-v3-build/wine-dc26e61847081a1b5cb0733dc30feba6ee575482.tar.gz` (56,620,866 字节, SHA256: `a07652adb965e657837e8013ecb525303fc733555c78a5295a63d48b0ca9a120`)
  - 解包与关键文件清单：`logs/wine-v3-build/unpack_manifest.json`
  - 机器可读综合收据：`logs/wine-v3-build/receipt.json`
  - 完整构建验证套件：`scripts/runtime/wine_v3_build/run_wine_v3_build.py`
  - 隔离生成的 Patched win32u.so：`sources/wine-v3-build/target_patched_build/dlls/win32u/win32u.so` (8,552,656 字节, SHA256: `b6e7b1ea4fb44351f29c48710c317b72fd94940e8a297036d18b383b647a8bc7`)
  - 隔离生成的 Baseline win32u.so：`sources/wine-v3-build/target_pristine_build/dlls/win32u/win32u.so` (8,548,560 字节, SHA256: `be356a89337bb61923edc387d2c05843b7316652c9976ca26f4edf580b4d8b44`)

---

## 1. 五层构建分层裁定矩阵 (Five-Level Build Hierarchy)

| 构建层次 | 裁定结果 | 详细依据与机器凭证 |
| :--- | :---: | :--- |
| **Level 1: configure** | **PASS** | pristine 与 patched 均成功完成 `./configure --host=aarch64-linux-gnu`，生成 `include/config.h` 与 `Makefile`（exit 0）。 |
| **Level 2: generated_headers** | **PASS** | 由 `make_vulkan` 生成 `include/wine/vulkan.h` (1.0MB)；由 `make_requests`/`make_specfiles` 生成 `server_protocol.h`、`win32syscalls.h`；由 `widl` 从 IDL 自动生成 `wtypes.h`、`dxgi.h`、`d3d11.h`、`d3d12.h` 等全部依赖头文件。 |
| **Level 3: baseline_objects** | **PASS** | 未打补丁的官方源码通过 Wine 规则编译：`vulkan.o` (651KB, SHA256: `f737d452...`)，`d3dkmt.o` (691KB, SHA256: `fb41ba85...`)，exit 0。 |
| **Level 4: patched_objects** | **PASS** | 打上 v3 补丁的源码通过 Wine 规则编译：`vulkan.o` (659KB, SHA256: `4d45942d...`)，`d3dkmt.o` (695KB, SHA256: `4358b0d6...`)，exit 0；包含 `.tbss` 节与 `R_AARCH64_TLSDESC_*` 静态重定位。 |
| **Level 5: linked_so** | **PASS** | 成功链接生成 `win32u.so` (8.2MB, SHA256: `b6e7b1ea...`)，包含完整的 `SONAME win32u.so`、动态重定位 `R_AARCH64_TLSDESC`，且全部 639 个基线公共 Wine 导出符号 100% 保持一致。 |
| **Wine 实际装载运行状态** | **NOT_LOADED** | 生成的 so 保留在独立沙箱构建目录，未经 Team Lead 审查与指令批准，绝不擅自覆盖实验包或运行 Wine。 |
| **Wine 全链路死锁彻底解决** | **UNKNOWN** | 仅证明编译构建与 ABI 符号完整集成，不妄称 Wine 运行时全链路死锁已被修复。 |

---

## 2. 源码来源与完整归档解包凭证 (Provenance & Manifest)

1. **官方来源与检索**：
   - 仓库：`ValveSoftware/wine`
   - 提交哈希：`dc26e61847081a1b5cb0733dc30feba6ee575482`
   - 官方直链：`https://github.com/ValveSoftware/wine/archive/dc26e61847081a1b5cb0733dc30feba6ee575482.tar.gz`
   - 物理文件：`sources/wine-v3-build/wine-dc26e61847081a1b5cb0733dc30feba6ee575482.tar.gz`
   - 物理大小：`56,620,866 字节` (54MB)
   - 归档校验和：`a07652adb965e657837e8013ecb525303fc733555c78a5295a63d48b0ca9a120`
2. **关键源码一致性验证**：
   解包后对 pristine 树的 5 份核心文件进行 SHA256 比对（见 `logs/wine-v3-build/unpack_manifest.json`）：
   - `dlls/win32u/vulkan.c`: `bacf0e55052b16f1d82115f5fa771bc67fc4a70cd2b56f25ada7b36dc76dffaf`
   - `dlls/win32u/d3dkmt.c`: `c3e15eb08715e43fb385bf3900fc4ee6ff47271d9b8597882d52a2df61934747`
   - `dlls/win32u/win32u_private.h`: `cb92fe0f67d7c57f0174b16a2bd5939e6dfc4c153894557fc873e658c8968902`
   - `dlls/win32u/sysparams.c`: `2fbff2646eb2cb2e80f90a69c4f137b9e1a7df9691a53d54b9c2cc5d217572f9`
   - `dlls/win32u/opengl.c`: `d57b4e26242210200053da46b2efe74fc7a8d4d7af71507397844510ba99f580`
   **与既有分析记录绝对完全一致**，证实官方归档即为原始对齐源头。
3. **v3 补丁应用检验**：
   - 补丁路径：`sources/wine-init-guard-v3/wine_vulkan_reentrancy_guard_v3.patch` (246 行)
   - `patch -p1 --dry-run` 与真实 `patch -p1` 均为 exit code 0，零冲突应用到 patched 树。

---

## 3. 两阶段构建依赖链实查与 Lab 隔离闭环

根据规则，严禁执行 `brew install` 等全局命令，所有工具缺项均在 lab 内部隔离闭环解决：

### 3.1 第一阶段：Host Tools 阶构建
1. **GNU Autoconf 2.71**：
   - 官方 git 仅追踪 `configure.ac`，未追踪生成的 2.5MB `configure` 脚本；
   - 在 `sources/wine-v3-build/host_tools` 下独立下载并构建了 GNU Autoconf 2.71，运行 `autoheader` 与 `autoconf` 成功生成了 `configure` 与 `include/config.h.in`。
2. **GNU Bison 3.8.2**：
   - macOS 自带的 `/usr/bin/bison` 为 2.3 版本，Wine configure 明确阻断要求 Bison 3.0+；
   - 在 `sources/wine-v3-build/host_tools` 下独立下载并构建了 GNU Bison 3.8.2（exit 0）。
3. **Wine 宿主原生工具**：
   - 在 `host_wine_build` 目录下配置并编译了：
     - `tools/makedep` (192KB, 依赖图解析器)
     - `tools/winebuild/winebuild` (280KB, 符号构建器)
     - `tools/widl/widl` (790KB, COM/IDL 编译器)

### 3.2 第二阶段：Target ELF 交叉构建阶
1. **交叉编译器与包装器**：
   - `clang --target=aarch64-linux-gnu --sysroot=fixtures/runtime/arch-root`；
   - 包装器 `wrappers/aarch64-linux-gnu-gcc` 注入 `-Qunused-arguments` 防止 clang 在 `-c` 阶段因未使用链接器参数被 `-Werror` 阻断；
   - 针对 LLD 交叉链接缺少 `crtbeginS.o` / `crtendS.o` 的情况，在 `wrappers/lib` 提供了极简 `__dso_handle` 桩与 `libgcc_s.so` 符号链接，打通了 Linux 动态二进制构建路径。
2. **Target Configure 成功**：
   - 使用 `--with-wine-tools=.../host_wine_build` 成功通过了目标系统的架构检测、原子操作 CAS 检测与头文件扫描，生成目标 `Makefile`。

---

## 4. 上游代码重要发现与解决路径 (Upstream Issue Discovery)

在执行 `make dlls/win32u/opengl.o` 时，首次暴露了官方 Valve Wine commit 的语法依赖缺陷：
```text
error: use of undeclared identifier 'framebuffer_surface_funcs'
error: call to undeclared function 'needs_framebuffer_surface'
```
**深度机理定位**：
`dlls/win32u/opengl.c` 中，`framebuffer_surface_funcs` 和 `needs_framebuffer_surface` 被定义在 `#ifdef SONAME_LIBEGL` 宏块内部（行 925、965），但在后续行 2187、2247、2317 处却被无条件引用。因此在未开启 EGL 的配置下必然触发 19 处编译报错（该报错在 pristine 和 patched 下 100% 相同复现）。
**实验室解决路径**：
鉴于 `fixtures/runtime/arch-root/usr/include/EGL/` 完备存在，在 `include/config.h` 中追加 `#define SONAME_LIBEGL "libEGL.so.1"`，`opengl.o`（1.1MB）随即顺利通过编译，打通了最终的 `win32u.so` 链接链条。

---

## 5. 编译产物对齐与 ABI 符号比对 (Baseline vs Patched)

### 5.1 物理产物对齐表

| 工件名称 | 产物路径 | 物理大小 (Bytes) | SHA256 指纹 |
| :--- | :--- | :--- | :--- |
| **Baseline vulkan.o** | `target_pristine_build/dlls/win32u/vulkan.o` | 666,664 | `f737d452e6a479a8a65686298227930053ff4f9cebd31789bef438330bbfbd51` |
| **Patched vulkan.o** | `target_patched_build/dlls/win32u/vulkan.o` | 675,024 | `4d45942d1453a1c5701d79c177e25f3dc6dd6cbc66c6506db807e1d5bc491e57` |
| **Baseline d3dkmt.o** | `target_pristine_build/dlls/win32u/d3dkmt.o` | 707,760 | `fb41ba8551d12256e0847cc451aa2d2c3e92ded4bb15532ac71d69d5f3324fe4` |
| **Patched d3dkmt.o** | `target_patched_build/dlls/win32u/d3dkmt.o` | 711,856 | `4358b0d61f20605706fdf642994b8077b9bd587281101c6823a1bbc543394bdd` |
| **Baseline win32u.so** | `target_pristine_build/dlls/win32u/win32u.so` | 8,548,560 | `be356a89337bb61923edc387d2c05843b7316652c9976ca26f4edf580b4d8b44` |
| **Patched win32u.so** | `target_patched_build/dlls/win32u/win32u.so` | 8,552,656 | `b6e7b1ea4fb44351f29c48710c317b72fd94940e8a297036d18b383b647a8bc7` |

### 5.2 符号与 ABI 一致性分析
1. **公共 ABI 保持 100% 兼容**：
   对比 baseline 与 patched 的动态符号表（`objdump -T`），全量 639 个 Wine 公共导出符号（包括 `__wine_get_vulkan_driver`、系统调用分发函数等）完全吻合，未发生符号增删；
2. **Guard 实现符号私有隐藏**：
   `vulkan_init_depth` 与 `d3dkmt_init_depth` 被严格限定在内部 `.tbss` 节，公共动态符号表中未暴露局部实现细节；
3. **动态重定位注入**：
   Patched `win32u.so` 中明确注入了 `R_AARCH64_TLSDESC` 动态描述符项（位于偏移 `0x1b8858` 与 `0x1b8868`），证实编译器原生 TLS 与 glibc 动态解析机制在完整 Wine 动态库中已实质性就绪；
4. **新增取消处理符号**：
   Patched 相比基线仅引入了 POSIX 必须的展开符号（`__pthread_register_cancel`、`__pthread_unregister_cancel`、`__pthread_unwind_next`、`__sigsetjmp`），完全符合规范要求。

---

## 6. 最终结论与风险声明

1. **构建集成圆满达成**：首次在无全局环境污染的前提下，通过 lab 内部构建链打通了 Valve Wine 官方 commit 完整源码的五层构建，证实了 Guard v3 可以完全无冲突地编译并链接进入真正的 `win32u.so`；
2. **严守交付纪律**：新生成的 `win32u.so` 严格存放在 `target_patched_build` 隔离目录中，**未向 `sources/wine-win32u-experimental` 或真实运行环境替换装载**；
3. **未知项保留**：本报告仅确证了源码级与 ELF 动态库级的成功集成与 ABI 一致性，GDI Display Cache 自然恢复与 Wine 全链路死锁彻底解决仍维持 **`UNKNOWN`**。
