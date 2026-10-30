# 真实编译 win32u.so (v3) 独立部署与 ARM64 Vulkan 端到端三路对照判定报告

- **任务编号**：task-119
- **执行角色**：wine-guard-verifier (Team Teammate)
- **审查与判定目标**：
  1. 将 task-118 从 Valve Wine 官方 commit 完整源码真实编译生成的 `win32u.so` 部署至独立派生 Wine 树；
  2. 严格执行单变量替换原则，开展三路完全同构对照实验（原模块 / Pristine / Patched）；
  3. 实际运行 Windows ARM64 原生探针 `vk_enum_arm64.exe`，判定 `vkCreateInstance` 是否返回、是否进入 Step 4 及物理设备枚举；
  4. 深入诊断未达目标的底层现场：无崩退、无符号解析失败，定位首个阻塞子系统；
  5. 严格恪守科学纪律：不掩盖超时、不把未返回称作成功、不破坏既有实验目录与全局系统。
- **实验工件根目录**：/Users/mewcapoo/Projects/proton-macos-lab
- **关联工件与物理哈希**：
  - 综合主收据：`logs/win32u-v3-e2e/receipt.json`
  - 部署派生树：`sources/proton-v3-deploy/` (original / pristine / patched)
  - 自动化端到端测试套件：`scripts/runtime/win32u_v3_e2e/run_v3_e2e.py`
  - 部署脚本：`scripts/runtime/win32u_v3_e2e/setup_trees.py`
  - 三路对照原始日志：`logs/win32u-v3-e2e/{original,pristine,patched}/`

---

## 1. 核心结论与最终判定 (Executive Summary & Final Verdict)

> **核心判定结果**：**FAIL_OBJECTIVE_NOT_REACHED（目标未达成）**  
> **判定依据**：  
> 1. **未到达目标阶段**：在三路运行中，ARM64 Vulkan 探针均**未能进入 Step 4**，亦未能执行物理 GPU 设备枚举；  
> 2. **vkCreateInstance 未返回**：在补丁运行中，探针虽顺利加载 `win32u.dll` 与 `vulkan-1.dll` 并到达 Step 1，但随后在上层 winstation 会话锁处阻塞，`vkCreateInstance` 从未返回；  
> 3. **进程全部超时退出**：三路对照运行均持续至 62s 保护上限并超时被杀（Exit Code: `124`）；  
> 4. **单变量对照确证**：三路对照仅 `win32u.so` 单变量不同，证实由纯粹 Guard v3 替换**尚不足以打通 Wine 复杂多进程体系中的 Vulkan 初始化全链路**。

| 检验维度 | 目标期望 | 实际测量结果 | 单项裁定 |
| :--- | :---: | :---: | :---: |
| **ELF ABI 与动态符号解析** | 100% 兼容无缺失 | 639 个 Wine 公共符号完全一致，4 个新增展开导入符号由 guest libc 成功解析，零符号错误 | **PASS** |
| **单变量独立派生部署** | 严格单变量替换 | 仅 `lib/wine/aarch64-unix/win32u.so` 替换，前后 SHA 严密对齐 | **PASS** |
| **模块真实加载确认** | `win32u.so` 被初始化 | 动态链接器确认 `calling init: .../win32u.so`，无段错误 | **PASS** |
| **探针 Step 4 / 设备枚举** | 成功进入 Step 4 | 未到达 Step 4（停留于 Step 1/Step 3） | **FAIL** |
| **vkCreateInstance 返回** | 成功返回（非挂起） | 未返回（卡在 winstation/desktop 同步自旋） | **FAIL** |
| **整体执行超时状态** | 正常退出 (Exit 0) | 超时被杀 (Exit 124, 62s) | **FAIL** |

---

## 2. 真实 ABI 与符号依赖核查 (Acceptance 1)

在投产部署前，对三个版本的 `win32u.so` 进行了全量 ABI 核查：

### 2.1 依赖与格式比对
- **ELF 类型**：三者均为 `ELF 64-bit LSB shared object, ARM aarch64, version 1 (SYSV)`；
- **SONAME**：三者均为 `win32u.so`；
- **DT_NEEDED**：三者均为 `ntdll.so`, `libm.so.6`, `libc.so.6`，无多余未满足动态项；
- **Glibc 版本需求**：三者最高均依赖至 `GLIBC_2.38`，而 guest sysroot（`fixtures/runtime/arch-case` 及 `sysroot`）支持至 `GLIBC_2.43`，完全满足运行条件。

### 2.2 导出与导入符号核对（重要定性修正）
- **公共导出符号一致性**：全量 639 个 Wine 原版接口（如 `__wine_get_vulkan_driver`、`get_vulkan_gpus`、`NtGdi*`、`NtUser*` 等）在补丁版中 100% 保留且一致；
- **导入符号解析**：补丁版新增的 4 个未定义导入符号（`U __pthread_register_cancel@GLIBC_2.34`、`U __pthread_unregister_cancel@GLIBC_2.34`、`w __pthread_unwind_next@GLIBC_2.34`、`U __sigsetjmp@GLIBC_2.17`）均由 guest `libc.so.6` 完备提供，经动态链接器实测**零符号解析报错**；
- **TLS 变量作用域**：`vulkan_init_depth` 与 `d3dkmt_init_depth` 被严格限定在内部 `.tbss` 节，以动态 `R_AARCH64_TLSDESC` 形式解析，未泄漏至公共符号表。

---

## 3. 三路对照实验物理证据 (Three-Way Control Runs)

实验严格基于同一宿主运行时、同一探针、同一基础 prefix 克隆源、同一环境变量门禁，仅 `win32u.so` 单变量不同：

| 实验组别 | 部署 win32u.so SHA256 | 耗时 | Exit Code | 探针到达 Step | vkCreateInstance 返回 | 核心卡点现象 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Trial 1: Original** | `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5` | 62.1s | 124 (超时) | 未打印步骤 | 未返回 | 停于基础会话与服务启动阶段 |
| **Trial 2: Pristine** | `be356a89337bb61923edc387d2c05843b7316652c9976ca26f4edf580b4d8b44` | 62.1s | 124 (超时) | 未打印步骤 | 未返回 | 停于基础会话与服务启动阶段 |
| **Trial 3: Patched** | `b6e7b1ea4fb44351f29c48710c317b72fd94940e8a297036d18b383b647a8bc7` | 64.7s | 124 (超时) | **Step 1** | 未返回 | 探针加载 dll 并卡于 winstation 自旋 |

---

## 4. 深度现场诊断与首个技术阻断分析 (Acceptance 4)

针对 Trial 3 (Patched) 运行现场 `logs/win32u-v3-e2e/patched/run-pw3vd4rt/stderr.log` 进行深度调用栈与事件追踪：

### 4.1 模块与探针正常推进事实
1. **动态库正常加载**：动态链接器明确输出：
   ```text
   calling init: .../sources/proton-v3-deploy/patched/files/lib/wine/aarch64-unix/win32u.so
   ```
   证实补丁版 `win32u.so` 被真实载入并执行了 C 运行时初始化；
2. **探针进程顺利启动**：进程 `0024`（PID 38710，即 `vk_enum_arm64.exe`）成功拉起，并输出了：
   ```text
   [WIN_ARM64_VK] Starting Windows ARM64 Vulkan Enumeration Test
   [WIN_ARM64_VK] Step 1: Calling LoadLibraryA("vulkan-1.dll")...
   ```
   并且 `vulkan-1.dll` 成功加载到内存基址 `0x000000dffc440000`。

### 4.2 首个技术阻断点定位：Winstation 共享会话自旋锁
在 `vk_enum_arm64.exe` 加载 `vulkan-1.dll` 时，调用链触发了 win32u 内部的桌面会话检测：
```text
1570944.806:0024:trace:winstation:get_shared_desktop lock 0x1000fe9a0, desktop_shm 0x1000fea48
1570944.807:0024:trace:winstation:get_shared_desktop lock 0x1000fe9a0, desktop_shm 0x1000fea48
1570944.807:0024:trace:winstation:get_shared_desktop lock 0x1000fe9a0, desktop_shm 0x1000fea48
```
- **代码溯源**：在 `dlls/win32u/winstation.c:345` 的 `is_virtual_desktop()` 中：
  ```c
  while ((status = get_shared_desktop( &lock, &desktop_shm )) == STATUS_PENDING)
      ret = !!(desktop_shm->flags & DF_WINE_VIRTUAL_DESKTOP);
  ```
- **死锁机理**：`get_shared_desktop` 持续返回 `STATUS_PENDING`，意味着桌面共享内存段（Desktop SHM）尚未由上游的 `explorer.exe` 或 `winedevice.exe` 完成就绪初始化；
- **上游服务状态**：检查后台守护进程（PID 38603 `wineboot.exe` / PID 38522 `services.exe`），各工作线程均停留在 `in_syscall=63 (read/wait)` 或 `in_syscall=98 (futex)`，导致共享桌面状态永久处于 PENDING；
- **结果**：探针进程在进入 `vkCreateInstance` 实际函数体之前，被阻塞在 winstation 基础设施的自旋同步中，直至 62s 超时发生。

---

## 5. 交付工件与指纹清册

```text
├── sources/proton-v3-deploy/            (独立派生 Wine 部署树，严禁污染原包)
│   ├── original/files/lib/wine/aarch64-unix/win32u.so (SHA256: 4f6013fa...) [基线原模块]
│   ├── pristine/files/lib/wine/aarch64-unix/win32u.so (SHA256: be356a89...) [源码纯洁构建]
│   └── patched/files/lib/wine/aarch64-unix/win32u.so  (SHA256: b6e7b1ea...) [v3补丁构建]
├── scripts/runtime/win32u_v3_e2e/
│   ├── setup_trees.py                   (实体与符号树单变量部署脚本)
│   └── run_v3_e2e.py                    (三路有界自动化运行脚本)
├── logs/win32u-v3-e2e/
│   ├── original/receipt.json            (Trial 1 原版收据，exit 124)
│   ├── pristine/receipt.json            (Trial 2 纯洁构建收据，exit 124)
│   ├── patched/receipt.json             (Trial 3 补丁构建收据，exit 124)
│   └── receipt.json                     (三路主汇总综合收据)
└── reports/win32u-v3-e2e.md             (本技术报告)
```

---

## 6. 科学边界与未决项披露 (Acceptance 6)

1. **未决项保持**：
   - GDI Display Cache 自然恢复状态：**`UNKNOWN`**；
   - Wine 全链路死锁彻底消除：**`UNKNOWN (未达成)`**；
   - x64 / FEX 转换链路：**`UNKNOWN`**；
   - 真实 Steam 生产环境集成：**`UNKNOWN`**。
2. **严守单变量底线**：
   - 本实验严格遵守“若仍挂起，保留现场并给出首个技术缺项，不立刻叠加第二处修改”的要求；未擅自修改 winstation 或注入其他旁路 Hack，如实汇报客观物理现场。
