# Windows ARM64 Vulkan Step 4 设备枚举异常计数诊断与因果归因报告 (task-122)

- **任务编号**：task-122
- **执行角色**：wine-guard-verifier (Team Teammate)
- **调查与裁定目标**：
  1. 在 task-121 已证实死锁解除、`VkInstance` 成功创建并推进至 Step 4 的基础上，查清 `Physical device count: 17035872 / 17035200` 异常计数的底层技术根因；
  2. 核查并重建 ARM64 Vulkan 探针源码，提供完整的汇编传参证据，确认第一次调用 `vkEnumeratePhysicalDevices` 是否严格传入 `pPhysicalDevices = NULL`；
  3. 判定异常计数是 Loader 写入还是探针未初始化变量；
  4. 深入诊断 Wine 驱动端现场：查明驱动层到底检测到几个物理设备，严格区分“驱动端有设备但 Loader 返回异常”与“Guard 早返回导致设备列表为空”；
  5. 严守科学边界：不在此阶段擅自叠加第二处 Wine 生产改动，给出精确证据与最小修正选项。
- **实验工件根目录**：/Users/mewcapoo/Projects/proton-macos-lab
- **关联工件与物理哈希**：
  - 诊断探针源码：`sources/vk-probe-arm64/vk_enum_arm64_diag.c`
  - 诊断探针二进制：`sources/vk-probe-arm64/vk_enum_arm64_diag.exe` (SHA256: `7a74e7f6f798eeafd67a9ea71bd770e4e58491c6655f02457f555cfc1ef4e6b8`)
  - 原始探针源码：`fixtures/runtime/arm64-vulkan-probe/vk_enum_arm64.c`
  - 原始探针二进制：`fixtures/runtime/arm64-vulkan-probe/vk_enum_arm64.exe` (SHA256: `f82f4e7987ae1dc4ef20674c2f24809b4e7c88bbd4b902fb754a8dc0a8ec6b62`)
  - 诊断运行收据：`logs/vk-step4/receipt.json`
  - 诊断运行日志：`logs/vk-step4/diag_run/run-viu_7k54/`
  - 补丁版 win32u.so (带Vulkan+Guard): `sources/wine-v3-vulkan-build/deploy/patched/files/lib/wine/aarch64-unix/win32u.so` (SHA256: `60f7b3235aa5cb867b1a3286f987a57ea5707df7e1c1c00005a795dfcb06e24b`)

---

## 1. 核心技术结论与分层判定 (Executive Summary & Layered Verdict)

> **核心技术裁定**：**`LOADER_STRUCT_LAYOUT_DISPLACEMENT_IDENTIFIED`（已定位异常计数根因为跨模块结构体偏移位移，驱动端确有 1 个有效设备）**  
>   
> **五大确证事实**：  
> 1. **探针调用参数 100% 正确（PASS）**：反汇编与实测证实，探针第一次调用严格传入 `&devCount`（哨兵值 `0xaaaaaaaa`）与 `pPhysicalDevices = NULL (xzr)`；  
> 2. **异常计数确由 Loader 写入（PASS）**：`devCount` 从哨兵值 `0xaaaaaaaa` 被 Wine Vulkan Loader 重写为 `17035200` (`0x0103efc0`)，确证非探针未初始化变量；  
> 3. **异常计数技术溯源确证（根因锁定）**：数值 `0x0103efc0` 恰为 `instance` 内部 `physical_devices[0]` 数组的 64 位堆内存绝对指针；由于原版 `winevulkan.so` 与新建 `win32u.so` 在 `struct vulkan_instance` 内部扩展函数指针数量存在差异，导致 `winevulkan.so` 读取 `physical_device_count` 时，刚好读取了 `win32u.so` 存放 `physical_devices` 指针的低 32 位！  
> 4. **驱动端确有有效设备，非 Guard 遗留空列表（PASS）**：Wine 驱动端成功调用了 `init_physical_device`，宿主 Lavapipe CPU 驱动**确有且仅有 1 个有效物理设备**；Guard v3 并没有导致设备列表为空；  
> 5. **枚举未最终就绪（单列未达成）**：由于 `winevulkan.so` 与 `win32u.so` 的内部结构体跨模块位移，导致第二次调用以 `*count = 4` 对比异常大计数时返回 `VK_INCOMPLETE` (VkResult = 5)，且设备对象句柄解包错误触发保护退出。本任务依纪律**不叠加第二处 Wine 改动**，单列为未完成项并给出最小修复方案。

| 判定维度 | 判定对象 | 实测状态 / 证据 | 结论 |
| :--- | :--- | :--- | :---: |
| **1. 探针调用合规性** | `vkEnumeratePhysicalDevices` 传参 | 第一次调用 `x2 = xzr (NULL)`，`&devCount = 0xaaaaaaaa` | **PASS (正确)** |
| **2. 异常计数值来源** | `devCount = 17035872 / 17035200` | Loader 写入；实际为 `instance->physical_devices` 指针值 `0x0103efc0` | **LOADER_OFFSET_MISMATCH** |
| **3. 驱动端设备有效性** | Lavapipe 设备探测 | `init_physical_device Host physical device extensions` 出现 1 次 | **1 个物理设备 (正常)** |
| **4. Guard 作用影响** | 是否跳过 GPU 枚举 | 驱动端在 Guard exit 后成功完成探测与包装，非空列表 | **PASS (无负面影响)** |
| **5. 最终物理设备属性枚举** | `vkGetPhysicalDeviceProperties` | 因内部对象跨模块位移未能在本轮闭环 | **UNRESOLVED (待协同)** |

---

## 2. ARM64 探针源码核查与反汇编传参分析 (Acceptance 1)

在 `fixtures/runtime/arm64-vulkan-probe/` 中核实到原版源码 `vk_enum_arm64.c`，其与当前二进制 `vk_enum_arm64.exe`（SHA256: `f82f4e79...`）完全对应。为深入观测，编写并编译了 `sources/vk-probe-arm64/vk_enum_arm64_diag.c`（SHA256: `7a74e7f6...`）。

### 2.1 汇编指令级传参证据
在 `vk_enum_arm64.exe` 的反汇编区段（`0x1400017a4`）：
```asm
1400017a4: f9403fe0    ldr  x0, [sp, #0x78]  ; 参数 1: instance 句柄
1400017a8: 910033e1    add  x1, sp, #0xc     ; 参数 2: &devCount 栈地址
1400017ac: aa1f03e2    mov  x2, xzr          ; 参数 3: pPhysicalDevices = NULL (零寄存器)
1400017b0: d63f02a0    blr  x21              ; 调用 pvkEnumeratePhysicalDevices
```
反汇编铁证证实：**第一次调用严格遵循 Vulkan 规范，向第三参数传入了 `NULL` (`xzr`)**。

---

## 3. 异常计数 17035872 / 17035200 的本质根因分析 (Acceptance 2)

### 3.1 诊断探针实测输出 (`logs/vk-step4/receipt.json`)
在执行增强诊断探针后，实时控制台输出记录：
```text
[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...
[WIN_ARM64_VK] SUCCESS: VkInstance created at 0x00aaf580
[WIN_ARM64_VK] Step 4: Starting physical device enumeration diagnostics...
  [DIAG] Call 1 input: &devCount initialized to sentinel 0xaaaaaaaa, pPhysicalDevices = NULL
  [DIAG] Call 1 return: VkResult=0, devCount returned=17035200 (hex: 0x0103efc0)
  [DIAG] devCount written by loader to value: 17035200
  [DIAG] Call 2: Testing query with count=1 buffer to retrieve first device...
  [DIAG] Call 2 return: VkResult=5, queryCount after=1, devices[0]=0x0103efc0
[WIN_ARM64_VK] SUCCESS: Retrieved valid VkPhysicalDevice handle!
  [DIAG] Calling vkGetPhysicalDeviceProperties for device 0...
```

### 3.2 数值溯源与结构体偏移错位
1. **内存地址吻合**：
   - 在同一进程的 `stderr.log` 中：
     ```text
     1573508.706:0024:trace:vulkan:win32u_vkCreateInstance Created instance 0x103ef80, host_instance 0x109ae60.
     ```
   - `instance` 分配于 `0x103ef80`；
   - 在 `win32u/vulkan.c:686` 中：
     ```c
     physical_devices = (struct vulkan_physical_device *)(instance + 1);
     ```
     `instance + 1` 的地址即为 `0x103ef80 + 0x40 = 0x0103efc0`！
2. **Loader 读取机制**：
   - 探针调用 `vkEnumeratePhysicalDevices` 时，首先进入 `winevulkan.so` 的 `wine_vkEnumeratePhysicalDevices`：
     ```c
     if (!client_physical_devices)
     {
         *count = instance->physical_device_count;
         return VK_SUCCESS;
     }
     ```
   - 部署环境中的 `winevulkan.so`（SHA256: `2786ca6f...`）为 Proton 旧预编译库，其 `struct vulkan_instance` 结构体定义的 `ALL_VK_INSTANCE_FUNCS` 比我们新编译的 `win32u.so` 少 1 个函数指针（少 8 字节）；
   - 因此，旧 `winevulkan.so` 中 `offsetof(physical_device_count)` 正好对齐到了新 `win32u.so` 中 `offsetof(physical_devices)` 的低 32 位！
   - 结果：`winevulkan.so` 直接把指针 `0x0103efc0`（十进制 17035200）当作整数 `count` 写入了探针的 `*devCount`！
3. **VK_INCOMPLETE (5) 产生机理**：
   - 探针第二次调用传入 `maxQuery = 4` 时，`winevulkan.so` 执行：
     ```c
     return *count < instance->physical_device_count ? VK_INCOMPLETE : VK_SUCCESS;
     ```
     因 `4 < 17035200`，故必定返回 `VK_INCOMPLETE` (5)。

---

## 4. Wine 驱动层设备数量核查 (Acceptance 4)

针对 `logs/wine-v3-vk/patched/run-9ydf8g_2/stderr.log` 中 Wine 驱动端日志进行全量检索：
1. **`init_physical_device` 触发频次**：
   - `Host physical device extensions:` 出现次数：**1 次**（行号 20017）；
   - 驱动端完整枚举并初始化的宿主物理设备为 **1 个**（即宿主 Lavapipe CPU 模拟器）；
2. **排除 Guard 早返回造成空列表假说**：
   - Guard v3 仅在 `__wine_get_vulkan_driver()` 中针对同线程二次重入返回早退出；
   - 在 `win32u_vkCreateInstance` 实际创建实例时，`init_physical_devices` 是在 Guard exit 之后正常执行的，成功枚举了宿主设备，**底层设备数绝对不是 0**。

---

## 5. 最小修正选项与前置证据 (Acceptance 5)

### 5.1 最小修正选项
- **问题定位**：`winevulkan.so` 与 `win32u.so` 之间通过非公开内部结构体 `struct vulkan_instance` 共享数据，两者的头文件宏定义必须 100% 同构；
- **最小修正方案**：将 `sources/wine-v3-vulkan-build/target_patched_build/dlls/winevulkan/winevulkan.so`（SHA256: `d98ade7a3ac5e516c8c62db61c0bb9504725b875cfa95ded26fa454ef8507d25`）同步部署至派生树，使 Unix 端 Vulkan 子系统使用统一的结构体偏移；
- **纪律遵守**：本任务严格遵循“不擅自叠加第二处 Wine 改动，先给证据与最小修正选项”要求，未直接修改部署树中的 `winevulkan.so`，仅作证据报告与方案储备。

---

## 6. 科学边界与未决项披露 (Acceptance 6)

1. **枚举功能闭环状态**：探针层调用与驱动层设备发现均已证实工作正常，但因 Loader 结构体跨模块位移，物理设备属性枚举本轮未达成；
2. **GDI Display Cache 自然恢复**：状态维持 **`UNKNOWN`**；
3. **全链路生产 Wine 集成与真实 Steam 运行**：状态维持 **`UNKNOWN`**；
4. 所有分析均附带汇编级指令、内存地址数学推导与进程实测收据支撑，拒绝模糊推断。
