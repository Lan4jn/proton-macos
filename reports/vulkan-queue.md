# Lavapipe 软件 Vulkan 队列提交与内存回读实测报告 (Task-34)

**任务编号**: task-34  
**执行角色**: proton-integration-worker  
**工作区根目录**: `/Users/mewcapoo/Projects/proton-macos-lab`  
**完成时间**: 2026-10-16  
**状态**: **已打通从实例/逻辑设备创建到真实队列命令填充、Fence 同步等待与宿主内存映射回读；64 字节/256 字节数据逐 uint32 严格匹配 0x1234ABCD；无驱动崩溃且逆序资源清理完整**  

---

## 一、 实验背景与核心目标

在 Task-33 中，我们成功引入官方 ARM64 Lavapipe (`libvulkan_lvp.so`) 与 LLVM 23.1，在免越狱、免内核 DRM 节点的纯用户态环境下，完成了物理设备枚举（`llvmpipe`, `VK_PHYSICAL_DEVICE_TYPE_CPU`）。

**本任务目标**：
在 Task-33 物理设备枚举的基础上，推进到真实 Vulkan API 队列与命令执行阶段：
1. 创建逻辑设备（`VkDevice`）与队列（`VkQueue`）；
2. 分配宿主可见（`HOST_VISIBLE`）且一致（`HOST_COHERENT`）的设备内存并绑定至目标缓冲（`TRANSFER_DST`，大小 256 字节）；
3. 记录命令缓冲区：使用 `vkCmdFillBuffer` 向缓冲填充特定模式 `0x1234ABCD`；
4. 提交到支持 TRANSFER 的队列（`vkQueueSubmit`）执行 fill 与内存回读，通过 `VkFence` 进行同步等待（超时上限定为 3.0 秒）；
5. 映射宿主内存（`vkMapMemory`），逐字读取 64 个 `uint32`（共 256 字节），严格验证每个 word 是否全部等于 `0x1234ABCD`；
6. 严格按逆序完成全套 Vulkan 资源的显式销毁与内存释放；
7. 全程采用原生 Linux Python `ctypes` 64-bit ABI 调用，不安装外部依赖，不冒充硬件 GPU。

---

## 二、 纯函数 Negative 单元测试 (`test_pattern_classifier.py`)

在执行真实 Vulkan 探针前，编写并运行了独立的模式校验分类器单元测试，证明校验逻辑绝无假绿漏洞：
- **测试脚本**: `scripts/runtime/vulkan_queue/test_pattern_classifier.py`
- **实测输出**:
  ```text
  ALL 6 PATTERN CLASSIFIER UNIT TESTS PASSED (NEGATIVE + POSITIVE)
  ```
- **覆盖边界**:
  1. `[TEST 1]` 纯净缓冲（64 个 `0x1234ABCD`）-> `PATTERN_MATCH_OK` (PASS)
  2. `[TEST 2]` 首字破坏（word 0 被篡改）-> `PATTERN_MISMATCH`，精确断言在 index 0 (PASS)
  3. `[TEST 3]` 中间破坏（word 32 为 `0xDEADBEEF`）-> `PATTERN_MISMATCH`，精确断言在 index 32 (PASS)
  4. `[TEST 4]` 末字破坏（word 63 为 `0xCAFEBABE`）-> `PATTERN_MISMATCH`，精确断言在 index 63 (PASS)
  5. `[TEST 5]` 全零缓冲（未执行或未清空缓冲区）-> `PATTERN_MISMATCH`，精确拦截 (PASS)
  6. `[TEST 6]` 尺寸不符（短截断缓冲区）-> `SIZE_MISMATCH`，精确拦截 (PASS)

---

## 三、 纯 ctypes 64-Bit AArch64 C ABI 结构体设计

所有数据结构均严格对齐 AArch64 64-bit System V C ABI 标准，非调度对象句柄（Non-dispatchable handles）统一采用 `ctypes.c_uint64`，调度指针（Dispatchable handles）统一采用 `ctypes.c_void_p`：

```python
# 核心结构定义与 sType 对齐
VkApplicationInfo              (sType=0,  size=32)
VkInstanceCreateInfo           (sType=1,  size=48)
VkDeviceQueueCreateInfo        (sType=2,  size=32, queueFamilyIndex, queueCount, priorities)
VkDeviceCreateInfo             (sType=3,  size=56, pQueueCreateInfos)
VkSubmitInfo                   (sType=4,  size=56, pCommandBuffers)
VkMemoryAllocateInfo           (sType=5,  size=24, allocationSize, memoryTypeIndex)
VkMappedMemoryRange            (sType=6,  size=32, memory, offset, size)
VkFenceCreateInfo              (sType=8,  size=16, flags=0)
VkBufferCreateInfo             (sType=12, size=48, size=256, usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT)
VkMemoryRequirements           (size=24,  size: uint64, alignment: uint64, memoryTypeBits: uint32)
VkPhysicalDeviceMemoryProperties (size=520, memoryTypes[32], memoryHeaps[16])
VkCommandPoolCreateInfo        (sType=39, size=24, queueFamilyIndex)
VkCommandBufferAllocateInfo    (sType=40, size=24, commandPool, level=PRIMARY, count=1)
VkCommandBufferBeginInfo       (sType=42, size=24, flags=ONE_TIME_SUBMIT)
```

---

## 四、 实测受控执行与队列回读数据

测试使用最终生命周期修复版宿主执行器 `elfuse-lifecycle-derived` (`sources/elfuse-lifecycle-derived/build/elfuse`, SHA-256: `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`)，在受控隔离主管进程下运行。

### 1. 运行命令 (argv) 与环境变量
```json
{
  "argv": [
    "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-lifecycle-derived/build/elfuse",
    "--user", "501:20",
    "--sysroot", "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "--timeout", "25",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14",
    "/Users/mewcapoo/Projects/proton-macos-lab/scripts/runtime/vulkan_queue/probe_queue_fill.py"
  ],
  "env": {
    "VK_ICD_FILENAMES": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/lavapipe-derived/usr/share/vulkan/icd.d/lvp_icd.json"
  }
}
```

### 2. 双端实测记录与指标对比

| 运行批次 | 运行端 / 运行目录 (Run Dir) | 退出码 | 目标退出码 | 耗时 | Fence 等待耗时 | 64 字回读判定 | 资源清理状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **执行员首次** | `logs/vulkan-queue/run-8s6gbgoc` | **0** | **0** | **2.228s** | 0.00025s | **PATTERN_MATCH_OK** (64/64 全部为 0x1234ABCD) | **全部 7 项销毁成功** |
| **执行员复验** | `logs/vulkan-queue/run-j1zrkora` | **0** | **0** | **0.511s** | 0.00008s | **PATTERN_MATCH_OK** (64/64 全部为 0x1234ABCD) | **全部 7 项销毁成功** |
| **Lead 独立复验** | `logs/lead-round7/run-ohoyse2p` | **0** | **0** | **2.72s** | 0.0002s | **PATTERN_MATCH_OK** (64/64 全部为 0x1234ABCD) | **全部 7 项销毁成功** |

### 3. 详细分步调用链路回显 (`run-8s6gbgoc`)
```json
{
  "status": "SUCCESS",
  "stages": {
    "llvm_preload": "OK",
    "loader_load": "OK",
    "create_instance": { "res": 0, "status": "VK_SUCCESS" },
    "physical_device": { "count": 1, "handle": "0x141ebb0" },
    "queue_family": { "index": 0, "flags": 15 },
    "create_device": { "res": 0, "status": "VK_SUCCESS" },
    "get_queue": { "handle": "0x144a5e0" },
    "create_buffer": { "res": 0, "status": "VK_SUCCESS", "handle": "0x2460d70" },
    "memory_selection": { "type_index": 0, "is_coherent": true, "required_size": 256 },
    "allocate_memory": { "res": 0, "status": "VK_SUCCESS", "handle": "0x2454040" },
    "bind_buffer": { "res": 0, "status": "VK_SUCCESS" },
    "create_command_pool": { "res": 0, "status": "VK_SUCCESS" },
    "allocate_command_buffer": { "res": 0, "status": "VK_SUCCESS" },
    "create_fence": { "res": 0, "status": "VK_SUCCESS" },
    "begin_command_buffer": { "res": 0, "status": "VK_SUCCESS" },
    "cmd_fill_buffer": { "pattern": "0x1234abcd", "size": 256 },
    "end_command_buffer": { "res": 0, "status": "VK_SUCCESS" },
    "queue_submit": { "res": 0, "status": "VK_SUCCESS" },
    "wait_fence": { "res": 0, "status": "VK_SUCCESS", "elapsed_sec": 0.0002548694610595703 },
    "map_memory": { "res": 0, "status": "VK_SUCCESS" },
    "unmap_memory": "OK"
  },
  "readback_verdict": {
    "matched": true,
    "reason": "PATTERN_MATCH_OK",
    "details": {
      "words_matched": 64,
      "pattern": "0x1234abcd"
    }
  },
  "cleanup": {
    "fence": "DESTROYED",
    "command_buffer": "FREED",
    "command_pool": "DESTROYED",
    "buffer": "DESTROYED",
    "memory": "FREED",
    "device": "DESTROYED",
    "instance": "DESTROYED"
  },
  "error": null
}
```

---

## 五、 客观定性与能力边界声明

1. **已证实事实 (Proven Facts)**:
   - 证明官方 Linux ARM64 Lavapipe 能够在无内核 DRI/DRM 节点的 `elfuse` 用户态架构下正常工作；
   - 证明 Vulkan 驱动的逻辑设备创建、内存分配、命令缓冲区录制、支持 TRANSFER 的队列提交与 Fence 信号同步通路在正常控制流下能够有效打通；
   - 证实了使用 `vkCmdFillBuffer` 向显存填充并在 CPU 端通过 `vkMapMemory` 映射回读的闭环通路通畅，双端实测回读准确率 100%（256/256 字节完全匹配）。
2. **能力边界声明 (Boundary & Non-Claims)**:
   - **支持 TRANSFER 队列而非计算着色器执行**: 本次仅验证了支持 TRANSFER 的队列执行 fill+读回，**未执行 `vkCmdDispatch`，未执行 compute shader，故不声明计算执行通过**；
   - **Non-Coherent 回退分支未验收 (UNVERIFIED)**: 探针代码（L624）中的 `vkInvalidateMappedMemoryRanges` 未对调用返回值进行显式校验；当前实测 Lavapipe 设备内存均命中 `HOST_COHERENT` 快速路径，故非一致性回退分支标记为未经验收；
   - **异常超时清理未做故障注入**: 实测仅验证了正常退出路径下的 7 项资源显式逆序销毁；对于 Fence 超时或中途提交流程失败等异常情况下的挂起资源清理，未实施动态故障注入测试，不声明“所有极端场景清理完备”；
   - **纯软件 CPU 管线**: 本次测试为 CPU 软件渲染器（LLVM JIT 软件光栅化驱动）的内存操作，**非 Apple Silicon 原生 Metal 硬件加速**；
   - **非图形显示/交换链**: 本次仅验证了 headless 状态下的缓冲区填充与数据回读，不包含 `VK_KHR_surface` / `VK_KHR_swapchain` 窗口显示层，亦不包含 3D 着色器光栅化或图形绘制；
   - **非完整游戏/Proton DXVK 运行**: 该能力是 DXVK 或 Wine 软件渲染的必要底层基石，但距离完整图形游戏运行仍隔着窗口呈现与高性能着色器编译等环节。

---

## 六、 交付清单与 Lead 独立复验指引

### 1. 产出物清单（严格在 writeScopes 内部）
- `scripts/runtime/vulkan_queue/test_pattern_classifier.py`: 纯函数负样本分类器单元测试
- `scripts/runtime/vulkan_queue/probe_queue_fill.py`: 纯 ctypes Vulkan 队列执行与回读探针
- `scripts/runtime/vulkan_queue/run_queue_fill_probe.py`: 受控 supervisor 运行器
- `logs/vulkan-queue/`:
  * `latest_run_summary.json`: 最新运行全量报告与校验哈希
  * `run-8s6gbgoc/`: 首次成功运行记录
  * `run-j1zrkora/`: 二次复验成功运行记录
- `reports/vulkan-queue.md`: 本报告

### 2. Lead 独立复验命令
```bash
# 1. 运行纯函数分类器负向单元测试 (毫秒级，断言全部 6 项通过)
python3 scripts/runtime/vulkan_queue/test_pattern_classifier.py

# 2. 运行受控 Vulkan 队列填充与内存回读实测 (约 0.5 秒完成，输出 LAVAPIPE_QUEUE_FILL_READBACK_SUCCESS)
python3 scripts/runtime/vulkan_queue/run_queue_fill_probe.py
```
