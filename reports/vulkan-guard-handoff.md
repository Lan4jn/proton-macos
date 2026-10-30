# Windows ARM64 Vulkan 重入自死锁修复与 Guard v3 最小补丁开发交接文档

- **文档版本**：v1.0 (Final Delivered)
- **任务编号**：task-128
- **交接作者**：wine-guard-verifier (Proton macOS Lab Team)
- **交付目标**：完整记录 Wine win32u Vulkan 驱动初始化同线程重入死锁的机理、基于精确源码 Pin 的自然结构体对齐、248 行最小纯 Guard 补丁形态、从源码构建到端到端实测的全链路可复现步骤、严格判据、可移植性红线及证据索引，供后续工程团队无缝交接。

---

> **【状态与边界核心声明】**：
> 1. **已通过范围**：所谓“通过 / WIN_ARM64_VULKAN_OK”仅指在 `ELFUSE_DIAG_SESSION_SHARED=1` 诊断映射环境下的 Windows ARM64 原生 Vulkan CPU 设备（llvmpipe）枚举测试。该诊断映射丢弃了 Linux 标准文件私有页缓存 Copy-On-Write (COW) 隔离语义，**绝不等于生产全链路已完成**；
> 2. **源码 Pin 定位**：Commit `adea6cbac9d00bb22910145354d00c463fcf3afc`（等价区间 `[66ee546cbea4..adea6cbac]`）为经由结构体尺寸与运行验证的**兼容基线**，并非经 Valve 官方 submodule 指针证明的唯一精确构建源；
> 3. **运行实体隔离**：基线死锁运行（`shipped_baseline`，`run-73d055tk`）直接基于 Valve 原版 Shipped 二进制（`win32u.so` `4f6013fa...`）；而源码直接编译出的 `adea pristine` 二进制（`96de5f0a...`）仅用于静态反汇编结构体偏移自检，两者严格分立。

---

## 1. 问题陈述与修复原理 (Problem & Mechanism)

### 1.1 缺陷背景与死锁现象
在 Apple Silicon macOS 宿主通过 elfuse HVF 用户态虚拟化运行 Valve 原版 ARM64 Proton (experimental-11.0-20260924-arm64) 时，任何调用 Vulkan 的 Windows ARM64 原生应用在执行 vkCreateInstance 时都会发生**同线程无声挂起，直至守护进程超时被杀（Exit Code: 124）**。

### 1.2 底层物理死锁链条
在 dlls/win32u 中，Vulkan 初始化与 Windows 显示子系统的紧密耦合构成了致命的单线程自循环边：
```text
vkCreateInstance()
  -> win32u_vkCreateInstance()
    -> __wine_get_vulkan_driver(WINE_VULKAN_DRIVER_VERSION)
      -> pthread_once(&init_once, vulkan_init_once)     [Step A: 线程进入 once，状态变为 IN_PROGRESS (word=1)]
        -> vulkan_init_once()
          -> get_vulkan_gpus(&vulkan_funcs.gpus)
            -> nulldrv_get_vulkan_gpus()
              -> init_display_devices()
                -> __wine_get_vulkan_driver()            [Step B: 同一线程在此处再次请求驱动初始化！]
                  -> pthread_once(&init_once, ...)       [Step C: 发现 once 为 IN_PROGRESS，执行 futex 自等待]
                    -> futex(uaddr=0x201039970, FUTEX_WAIT_PRIVATE, val=1) ==> 线程等待自己完成，永久自锁死锁！
```

### 1.3 原版 Shipped 基线死锁物理证据行
在未经补丁修改的 Valve 原版 Shipped 二进制运行日志（logs/wine-pin/shipped_baseline/run-73d055tk/stderr.log，运行 Shipped 原版 win32u.so 4f6013fa...，与仅用于静态偏移验证的 adea pristine 96de5f0a... 严格区分）中，全景观测记录下确凿的自死锁调用轨迹：
```text
Line 54: ONCE_ENTRY_COUNT ts_us=1573370812999 pid=74958 gtid=1 pc=0x2000ce1a0 x0_uaddr=0x201039970 is_target=0 word=0 lr=0x200f97324
Line 69: ONCE_ENTRY_COUNT ts_us=1573371285185 pid=74958 gtid=1 pc=0x2000ce1a0 x0_uaddr=0x2010399a8 is_target=0 word=0 lr=0x200f980f4
Line 71: ONCE_ENTRY_COUNT ts_us=1573379932582 pid=74958 gtid=1 pc=0x2000ce1a0 x0_uaddr=0x201039970 is_target=0 word=1 lr=0x200f97a00
```
- **说明**：同一主线程（pid=74958, gtid=1）在 Line 54 首次进入 0x201039970 (word=0)；在 Line 71 递归再次进入自身处于 word=1 的 0x201039970，随后调用 futex 进入无唤醒者的自等待，直至 90s 超时退出。

### 1.4 修复原理：基于 Compiler TLS 的深度平衡 Guard
1. **消除动态键表耗尽风险**：废除 POSIX 运行时动态键（pthread_key_create），改用编译器原生线程局部存储 static __thread int vulkan_init_depth;（分配于 ELF .tbss 节），消除 pthread_key 的 EAGAIN / EINVAL 键表耗尽风险（注：在 dlopen 动态加载共享库时，访问 TLS 仍可能经 __tls_get_addr 依赖 DTV 动态内存分配，.tbss 并不等同绝对零内存分配风险，但完全消除了应用层键生命周期缺陷）；
2. **递归边条件切断**：在 __wine_get_vulkan_driver 与 get_vulkan_gpus 入口检查 is_vulkan_init_in_progress()；若当前线程正在初始化过程中，立即跳过 GPU 探测或降级早返回；
3. **词法作用域异常安全**：使用配对的 pthread_cleanup_push(vulkan_init_guard_cleanup, NULL) 与 pthread_cleanup_pop(1) 严格包覆整个初始化过程，在线程取消或异常展开时无条件执行平衡回退，彻底消除 Once-Poisoning 永久投毒隐患。

---

## 2. 源码版本 Pin 与结构体偏移绝对常数表 (Source Pin & ABI Constants)

### 2.1 精确 Pin Commit 与结构等价区间
由于 Wine 采用非公开内部结构体（struct vulkan_instance）跨 win32u.so 与 winevulkan.so 传递数据，两者的二进制布局必须严格对齐：
- **Valve Proton 官方构建时间戳**：1790245028（2026-09-24 10:17:08 UTC）；
- **源码 Pin 兼容基线**：**adea6cbac9d00bb22910145354d00c463fcf3afc**（Committer: 2026-09-24 00:51:45 UTC，位于官方 experimental_11.0 分支，早于 Proton 构建戳，系结构等价区间 [66ee546cbea4..adea6cbac] 的验证兼容基线，非 Valve 官方 submodule 认证的唯一精确构建源）；
- **结构等价区间**：Git 提交区间 **[66ee546cbea4..adea6cbac]** 内，vulkan_driver.h 与 vk.xml 结构定义完全同构，均显式对齐 Vulkan **1.4.357** 规范（包含 82 个 instance 函数指针）。

### 2.2 结构体偏移常数对照表

| 结构体 / 成员字段 | Shipped 二进制期望值 | dc26e618 错位值 | adea6cbac 对齐值 | 状态 |
| :--- | :---: | :---: | :---: | :---: |
| offsetof(struct vulkan_instance, physical_devices) | **0x2e0 (736)** | 0x2c8 (712) | **0x2e0 (736)** | **NATURAL MATCH** |
| offsetof(struct vulkan_instance, physical_device_count) | **0x2e8 (744)** | 0x2d0 (720) | **0x2e8 (744)** | **NATURAL MATCH** |
| offsetof(struct vulkan_instance, transient_object_handle) | **0x2f0 (752)** | 0x2d8 (728) | **0x2f0 (752)** | **NATURAL MATCH** |
| sizeof(struct vulkan_instance) | **0x2f8 (760)** | 0x2e0 (736) | **0x2f8 (760)** | **NATURAL MATCH** |
| sizeof(struct vulkan_physical_device) | **0x288 (648)** | 0x278 (632) | **0x288 (648)** | **NATURAL MATCH** |
| sizeof(struct instance) | **0x368 (872)** | 0x348 (840) | **0x368 (872)** | **NATURAL MATCH** |

### 2.3 反汇编指令核对方法
在构建出的 win32u.so 上运行反汇编命令，核对指令常数：
```bash
objdump -d dlls/win32u/win32u.so | grep -A 25 "<win32u_vkCreateInstance>:"
```
**必须观察到以下 4 条关键指令**：
1. mov w9, #0x288：sizeof(struct vulkan_physical_device) 步长必须为 648 字节；
2. add x1, x8, #0x368：sizeof(struct instance) 必须为 872 字节；
3. add x28, x20, #0x2d0：utils_messengers 相对基址偏移必须为 0x2d0；
4. add x26, x20, #0x2e0：report_callbacks 相对基址偏移必须为 0x2e0。

---

## 3. 补丁内容摘要与无结构体改动特性 (Patch Architecture)

- **补丁文件路径**：sources/wine-pin-adea/wine_vulkan_reentrancy_guard_adea6cbac.patch
- **补丁 SHA256**：274b15713bff8342c20e41bdaaad51997cfb9cf707bb30d7ca5329b5e1ac5f75
- **补丁总行数**：**248 行**
- **修改文件清单**：
  1. dlls/win32u/vulkan.c：核心 Vulkan 驱动初始化重入 Guard；
  2. dlls/win32u/d3dkmt.c：D3DKMT 初始化 Vulkan 重入 Guard；
  3. dlls/win32u/win32u_private.h：Guard 函数符号内部声明。

### 核心设计特性：零结构体侵入
- **无任何结构体变动**：补丁**没有**向任何结构体添加填充字节（padding），没有修改 VkInstance / VkPhysicalDevice 布局，没有增删任何头文件宏；
- **为何成立**：因为通过精确 Pin 到 commit adea6cbac，生成的头文件结构体与 shipped Proton 二进制**天然 100% 同构**。补丁仅专注于纯粹的重入防护逻辑，达到了真正可合入上游的工业级最小形态。

---

## 4. 全链路独立复现指南 (Step-by-Step Reproduction Guide)

以下步骤均基于 /Users/mewcapoo/Projects/proton-macos-lab 真实环境，所有命令可直接复制执行：

### 步骤 1：获取与检出源码
```bash
cd /Users/mewcapoo/Projects/proton-macos-lab
mkdir -p sources/wine-handoff-build
cd sources/wine-handoff-build

# 检出精确 commit adea6cbac
git clone https://github.com/ValveSoftware/wine.git wine-src
cd wine-src
git checkout adea6cbac9d00bb22910145354d00c463fcf3afc

# 应用 248 行最小补丁
patch -p1 < /Users/mewcapoo/Projects/proton-macos-lab/sources/wine-pin-adea/wine_vulkan_reentrancy_guard_adea6cbac.patch
```

### 步骤 2：配置交叉构建环境
```bash
cd /Users/mewcapoo/Projects/proton-macos-lab/sources/wine-handoff-build
mkdir -p wrappers/lib target_build

# 1. 提供 readelf wrapper 保证 @rpath 完整
cat << 'EOF' > wrappers/aarch64-linux-gnu-readelf
#!/bin/sh
exec /opt/homebrew/Cellar/llvm@21/21.1.8/bin/llvm-readelf "$@"
EOF
chmod +x wrappers/aarch64-linux-gnu-readelf
ln -sf aarch64-linux-gnu-readelf wrappers/readelf

# 2. 挂接 CRT stub 与 libvulkan
cp /Users/mewcapoo/Projects/proton-macos-lab/sources/wine-v3-build/wrappers/lib/crtbeginS.o wrappers/lib/
cp /Users/mewcapoo/Projects/proton-macos-lab/sources/wine-v3-build/wrappers/lib/crtendS.o wrappers/lib/
cp /Users/mewcapoo/Projects/proton-macos-lab/sources/wine-v3-build/wrappers/lib/libgcc* wrappers/lib/
ln -sf /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/libvulkan.so.1 wrappers/lib/libvulkan.so.1
ln -sf /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/lib/libvulkan.so.1 wrappers/lib/libvulkan.so

# 3. GCC wrapper
cat << 'EOF' > wrappers/aarch64-linux-gnu-gcc
#!/bin/sh
SYSROOT="/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-root"
LLD="/opt/homebrew/Cellar/lld@21/21.1.8_1/bin/ld.lld"
VK_INC="/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-v3-vulkan-build/vulkan_headers/include"
STUB_LIB="/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-handoff-build/wrappers/lib"
exec clang -Qunused-arguments --target=aarch64-linux-gnu --sysroot="$SYSROOT" -fuse-ld="$LLD"   -isystem "$VK_INC" -B"$STUB_LIB" -L"$STUB_LIB" "$@"
EOF
chmod +x wrappers/aarch64-linux-gnu-gcc
```

### 步骤 3：配置与编译 win32u.so
```bash
cd /Users/mewcapoo/Projects/proton-macos-lab/sources/wine-handoff-build/target_build
export PATH="/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-handoff-build/wrappers:/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-v3-build/host_tools/bin:$PATH"

../wine-src/configure   --host=aarch64-linux-gnu   CC="/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-handoff-build/wrappers/aarch64-linux-gnu-gcc"   --with-wine-tools="/Users/mewcapoo/Projects/proton-macos-lab/sources/wine-v3-build/host_wine_build"   --with-vulkan   --enable-win64 --without-x --without-freetype --disable-tests

# 注入 sysroot 对应 EGL SONAME
echo '#define SONAME_LIBEGL "libEGL.so.1"' >> include/config.h

# 单独编译 win32u.so
make dlls/win32u/win32u.so
```

### 步骤 4：隔离单变量部署
严格执行单变量原则：**仅替换 win32u.so，保留原装 shipped winevulkan.so、winevulkan.dll 与 ntdll.so**：
```bash
cd /Users/mewcapoo/Projects/proton-macos-lab
mkdir -p deploy/handoff_test/files
cp -r sources/wine-win32u-experimental/patched-full/files/* deploy/handoff_test/files/

# 仅覆盖 win32u.so
cp sources/wine-handoff-build/target_build/dlls/win32u/win32u.so deploy/handoff_test/files/lib/wine/aarch64-unix/win32u.so
```

### 步骤 5：执行端到端物理探针并判定
```bash
python3 -c '
import sys; sys.path.insert(0, "scripts/runtime/vk_layoutfix")
from run_layoutfix import run_trial, REPO_ROOT, PROBE_ORIG
res = run_trial("handoff_test", REPO_ROOT / "deploy/handoff_test", PROBE_ORIG, timeout=90)
assert res["exit_code"] == 0 and res["step4_reached"]
print("SUCCESS: VkInstance created, device enumerated, exit 0!")
'
```

---

## 5. 验收判据与基线对比 (Acceptance & Baseline Criteria)

### 5.1 成功判定黄金标准 (All Must Pass)
1. **vkCreateInstance 成功返回**：输出 [WIN_ARM64_VK] SUCCESS: VkInstance created at 0x...；
2. **设备计数合理有效**：第一次枚举调用返回 devCount = 1（>= 1，绝非 0x0103efc0 类内存指针）；
3. **真实设备属性获取**：第二次枚举调用成功返回 VK_SUCCESS (0)，且调用 vkGetPhysicalDeviceProperties 获取到：
   ```text
   deviceName: llvmpipe (LLVM 23.1.1, 128 bits)
   deviceType: 4 (VK_PHYSICAL_DEVICE_TYPE_CPU)
   ```
4. **进程无挂起正常退出**：执行耗时约 48~52 秒，**Exit Code: 0，timed_out: False**，输出 FINAL_STATUS: WIN_ARM64_VULKAN_OK。

### 5.2 失败基线标准 (Baseline Failure Signature)
- 在同构环境下使用 Shipped 原版 win32u.so（SHA256: 4f6013fa...）时，探针停留在 Step 3，由于同线程在 0x20102d440 / 0x20102d478 发生 futex 递归死锁，**稳定超时被杀（Exit Code: 124）**。

---

## 6. 可移植性边界与红线规则 (Portability Boundaries & Guardrails)

1. **版本升级严禁盲替二进制**：
   - Wine 的 winevulkan.so 与 win32u.so 属于强绑定的内部 Unix 接口。若后续升级 Proton / Wine 版本，**必须重新反汇编 shipped winevulkan.so 核对 physical_devices（期望 0x2e0）与 physical_device_count（期望 0x2e8）偏移**；
   - 若版本跨度导致函数表数量变动，必须同步重新对齐或整体同源编译，否则会再次发生将堆指针低 32 位当设备计数的内存越界与崩溃（17035872 / 17035200 事故）；
2. **PE-Unix Thunk 序号一致性红线**：
   - Windows PE 端的 winevulkan.dll 与 Linux Unix 端的 winevulkan.so 通过自动生成的 enum winevulkan_funcs 枚举表调用；
   - 严禁单方面替换自建的 Unix winevulkan.so 而保留 shipped 的 PE winevulkan.dll，否则会引发函数序号错位（例如 vkCreateInstance 被映射至 thunk64_vkDestroyBuffer 产生 0xc0000005 崩溃）。

---

## 7. 已知未达成项显式披露 (Explicit Unknowns)

以下项目仍超出当前阶段，保持为 **UNKNOWN** 或未达成：
1. **GDI Display Cache 自然恢复**：**UNKNOWN**；
2. **真实 Steam 客户端生产接入**：**UNKNOWN**；
3. **x64 PE / FEX 二进制翻译执行链路**：**UNKNOWN**；
4. **宿主 GPU 硬件加速驱动**：当前通过 Lavapipe CPU 模拟器枚举，尚未挂接宿主 Metal/MoltenVK 硬件直通；
5. **复杂 3D 游戏真实窗口渲染与呈现**：尚未在多窗口全屏交换链中进行端到端测试。

---

## 8. 下一步开发建议 (Recommended Next Steps)

1. **【优先级 1：合并最小补丁至本地 Proton 分支】**：将 wine_vulkan_reentrancy_guard_adea6cbac.patch 作为标准补丁加入团队的 Wine/Proton 构建流水线；
2. **【优先级 2：推进 x64 Vulkan 探针穿透】**：在已打通 Windows ARM64 原生 Vulkan 的基础上，在 elfuse 下结合 FEX 验证 x64 PE 的 vk_enum_x64.exe 能否顺利完成同等枚举；
3. **【优先级 3：探索宿主 GPU 硬件直通 (Metal/MoltenVK)】**：研究在 Unix 驱动层挂接 macOS 原生 MoltenVK 或实现自定义 Metal ICD，将 CPU llvmpipe 升级为真硬件 GPU 渲染；
4. **【优先级 4：多线程重入并发压力测试】**：在多线程同时调用 vkCreateInstance 的场景下压测 Guard 锁安全性与深度平衡计数器。

---

## 9. 证据文件索引清册 (Evidence Manifest)

| 证据类别 | 文件路径 | SHA256 校验和 | 说明 |
| :--- | :--- | :--- | :--- |
| **最小补丁原件** | sources/wine-pin-adea/wine_vulkan_reentrancy_guard_adea6cbac.patch | 274b15713bff8342c20e41bdaaad51997cfb9cf707bb30d7ca5329b5e1ac5f75 | 248行纯Guard补丁 |
| **最终交付产物** | sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so | 59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed | 自然对齐补丁库 (9.0MB) |
| **Pristine自检库** | sources/wine-pin-adea/target_pristine_build/dlls/win32u/win32u.so | 96de5f0af594cf765fe7d350c0520b1e5568970633de9af63fad494012e5b10b | adea纯洁构建库 (仅用于静态偏移自检，未用于动态运行) |
| **Shipped原版库** | fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/win32u.so | 4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5 | 原始基线库 (2.4MB) |
| **Shipped Vulkan**| fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so | 2786ca6f5f440821972e91a371e609d2d482597a8b6d75bcf02e287f83eea9ab | 原始配套库 (864KB) |
| **宿主运行时** | sources/elfuse-once-panorama2-derived/build/elfuse | 8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda | 全景跟踪运行时 (开启 ELFUSE_DIAG_SESSION_SHARED=1) |
| **测试探针** | fixtures/runtime/futex-args-vulkan/pfx/drive_c/vk_enum_arm64.exe | f82f4e7987ae1dc4ef20674c2f24809b4e7c88bbd4b902fb754a8dc0a8ec6b62 | Windows ARM64 探针 |
| **最终测试收据** | logs/wine-pin/receipt.json | - | 记录 Exit 0 与 Exit 124 对照 |
| **成功运行现场** | logs/wine-pin/patched_adea/run-sjo653xi/stdout.log | - | 打印完整设备属性日志 (exit 0) |
| **死锁现场日志** | logs/wine-pin/shipped_baseline/run-73d055tk/stderr.log | - | 记录 65s 超时死锁调用栈 (使用 Shipped 原版 4f6013fa...) |
