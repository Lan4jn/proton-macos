# Windows ARM64 Vulkan 离屏三角形绘制与像素读回验证报告 (task-135)

- **任务编号**：task-135 (Full Robustness & Dual Negative Test Complete)
- **执行角色**：wine-guard-verifier (Proton macOS Lab Team)
- **核心判定**：**`WIN_ARM64_VULKAN_OFFSCREEN_PIPELINE_VERIFIED`**

---

## 1. 核心判定与执行摘要 (Executive Summary & Verdict)

> **七层全状态判定 (Seven-Layered Full Verdicts)**：
> 1. **安装计划与部署管线 (`installation_pass`)**：**PASS**（综合计划生成、部署、校验与完全回滚全流程 100% 验证）
> 2. **适配器迁移执行管线 (`adapter_execution_pass`)**：**PASS**（安装源目录移走后，安装目标 wrapper 独立正常启动）
> 3. **Vulkan 设备枚举 (`vulkan_enumeration_pass`)**：**PASS**（枚举并选取 CPU 设备 `llvmpipe (LLVM 23.1.1, 128 bits)`）
> 4. **图形管线绘制与同步 (`vulkan_offscreen_draw_pass`)**：**PASS**（RenderPass + Framebuffer + Graphics Pipeline + `vkCmdDraw(3)` 绘制三角形 + Fence 同步等待 10s 保护）
> 5. **像素精确读回校验 (`pixel_verification_pass`)**：**PASS**（16,384 字节原始缓冲区落盘，多点采样验证内部纯红三角形与外部深蓝背景）
> 6. **校验器合成负测试 (`synthetic_negative_tests_pass`)**：**PASS**（防伪测试确证：纯 Clear 假阴性、颜色篡改及数据截断均被校验器 100% 拦截）
> 7. **真实 PE 驱动执行负对照 (`real_pe_skip_draw_negative_pass`)**：**PASS**（真实 Windows ARM64 PE 传参 `--skip-draw` 执行，跳过 `vkCmdDraw`，客态探针自行检测出内部像素非红，明确以退出码 21 报错中止，绝不以纯 Clear 假冒成功）

---

## 2. 探针稳健性加固与架构说明 (Robustness Enhancements)

### 2.1 全量 API 返回码校验 (Zero Unchecked APIs)
对 `vk_offscreen_arm64.c` 进行了全量系统调用与 Vulkan API 审查，消除了所有未校验调用的隐患：
- `vkMapMemory`（顶点与 Staging 缓冲区）：严格校验返回值 `res == VK_SUCCESS` 及有效指针，失败退出码 18/20；
- `vkInvalidateMappedMemoryRanges`：严格校验返回值 `res == VK_SUCCESS`，失败退出码 20；
- `vkCreateBuffer` / `vkBindBufferMemory` / `vkAllocateMemory`：全部纳入返回值校验，失败退出码 18；
- `vkCreateCommandPool` / `vkAllocateCommandBuffers` / `vkBeginCommandBuffer` / `vkEndCommandBuffer`：全部纳入返回值校验，失败退出码 19；
- `vkCreateFence` / `vkQueueSubmit` / `vkWaitForFences`：全部纳入返回值校验，失败退出码 20；
- `CreateFileA` / `WriteFile`：严格校验文件句柄、布尔返回值以及实际写入字节数 `wrote == FB_SIZE`（16,384 字节），任何磁盘写入缺损均以退出码 23 报错中止。

### 2.2 内存映射与 Invalidate 范围一致性设计 (Mapping & Invalidation Rationale)
- **机制背景**：根据 Vulkan 1.0 规范，`vkInvalidateMappedMemoryRanges` 在传入 `size = VK_WHOLE_SIZE` 时，代表从指定 offset 起直至该 memory allocation 末尾；规范严格要求被 invalidate 的物理内存范围必须处于当前已 mapped 的区间内；
- **加固实现**：在 Staging Buffer 映射时，直接将整个分配容量 `sbMemReqs.size`（从 offset 0）全部映射：
  `res = pvkMapMemory(device, stagingBufferMemory, 0, sbMemReqs.size, 0, (void**)&pixels);`
  并在 invalidation 时指定：
  `range.offset = 0; range.size = VK_WHOLE_SIZE;`
- **技术依据**：由于已映射范围涵盖了分配的全部字节，`VK_WHOLE_SIZE` 严格与映射范围 100% 对齐，杜绝了由于分配对齐粒度导致 Invalidate 超出 Mapped 边界的潜在驱动未定义行为。

### 2.3 真实 PE 命令行解析与 `--skip-draw` 驱动负对照
- **独立实现**：在无 MSVC CRT 依赖的独立 PE 环境下，通过导入 Win32 API `GetCommandLineA()` 动态捕获命令行；
- **负对照机制**：当传入 `--skip-draw` 时，探针在 RenderPass 内显式跳过 `vkCmdDraw`（仅保留 Clear），随后正常提交、等待 Fence、读回像素。探针自检逻辑捕获到采样点 `(32, 38)` 呈现深蓝色而非纯红色，输出：
  `[INTERIOR (32,38)] Observed: R=0 G=0 B=128 A=255 -> MISMATCH! Expected Triangle Color`，并立即以退出码 21 退出；
- **双重负测试区隔**：
  * **校验器合成负测试 (`verify_pixels.py`)**：针对像素校验算法本身的抗干扰能力（纯蓝、假绿、截断）；
  * **真实 PE 负对照 (`--skip-draw`)**：针对真实驱动与绘制管线的因果性测试，确证只有真实绘制了三角形的 PE 进程才能以退出码 0 通过。

---

## 3. 探针编译与 Shader 工具链 (Probe Binary & Shader Manifest)

### 3.1 Windows ARM64 PE 独立探针
- **源码路径**：`sources/vk-offscreen-probe/vk_offscreen_arm64.c`
- **构建产物**：`sources/vk-offscreen-probe/vk_offscreen_arm64.exe`
- **架构与格式**：`PE32+ executable (console) Aarch64, for MS Windows`
- **最新二进制 SHA256**：`112377ef135b5bb3d240646b665b1747bc21078ec8ee2272208bec2c1ae11e22`
- **导入库构建**：`sources/vk-offscreen-probe/kernel32.def` 经 `llvm-lib` 生成包含 `GetCommandLineA` 的 `kernel32-arm64.lib`；
- **编译器与链接器**：`clang -target aarch64-windows` + `lld-link`。

### 3.2 着色器汇编与官方 SPIR-V 校验
- **顶点着色器**：`sources/vk-offscreen-probe/shaders/triangle.vert.spvasm` -> `triangle.vert.spv`（SHA256: `e5170e632079a1770df89598258ef89570e397da3d533530fe559adb598e9b91`）；
- **片段着色器**：`sources/vk-offscreen-probe/shaders/triangle.frag.spvasm` -> `triangle.frag.spv`（SHA256: `1a7ea883781c68884041cf223e181be962170bc784ff5d9df2d891e90eda4e36`）；
- **验证状态**：官方 `spirv-val --target-env vulkan1.0` 100% 校验通过；
- **构建脚本**：`sources/vk-offscreen-probe/build.sh`。

---

## 4. 图形管线与像素读回物理证据 (Graphics Pipeline & Pixels)

### 4.1 原始 Framebuffer 属性
- **容量大小**：16,384 字节（`64 × 64 × 4`）；
- **字节 SHA256**：`2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050`；
- **落盘路径**：`logs/vk-offscreen/framebuffer.raw`；
- **可视化图片**：经由内置 Python Pillow 生成 `logs/vk-offscreen/framebuffer.png` 与 4 倍无损放大图 `logs/vk-offscreen/framebuffer_256.png`。

### 4.2 采样点坐标与真实比对数据

| 采样区域 | 像素坐标 `(X, Y)` | 几何位置说明 | 实测观测值 `(R, G, B, A)` | 期望色值与类型 | 比对判定 |
| :--- | :---: | :--- | :---: | :--- | :---: |
| **内部 (三角形)** | `(32, 38)` | 三角形质心 Centroid (NDC 0.0, 0.2) | `(255, 0, 0, 255)` | 纯红 (Triangle Red) | **MATCH** |
| **内部 (三角形)** | `(32, 25)` | 三角形上部中点 (NDC 0.0, -0.2) | `(255, 0, 0, 255)` | 纯红 (Triangle Red) | **MATCH** |
| **内部 (三角形)** | `(22, 44)` | 三角形左下内部 (NDC -0.3, 0.4) | `(255, 0, 0, 255)` | 纯红 (Triangle Red) | **MATCH** |
| **内部 (三角形)** | `(42, 44)` | 三角形右下内部 (NDC 0.3, 0.4) | `(255, 0, 0, 255)` | 纯红 (Triangle Red) | **MATCH** |
| **外部 (背景)** | `(5, 5)` | 左上角背景，远离几何边缘 | `(0, 0, 128, 255)` | 深蓝 (Clear Background) | **MATCH** |
| **外部 (背景)** | `(58, 5)` | 右上角背景，远离几何边缘 | `(0, 0, 128, 255)` | 深蓝 (Clear Background) | **MATCH** |
| **外部 (背景)** | `(5, 58)` | 左下角背景，远离几何边缘 | `(0, 0, 128, 255)` | 深蓝 (Clear Background) | **MATCH** |
| **外部 (背景)** | `(58, 58)` | 右下角背景，远离几何边缘 | `(0, 0, 128, 255)` | 深蓝 (Clear Background) | **MATCH** |

---

## 5. 端到端双轮实跑与完全回滚实测 (Dual Real Execution & Rollback)

- **执行脚本**：`scripts/runtime/vk_offscreen/run_vk_offscreen.py`；
- **可迁移性实测**：将安装源目录彻底移走（`source_pkg_MOVED_AWAY`），直接执行安装目标 wrapper；
- **双轮执行数据**：
  * **轮次 1（正常绘制）**：耗时 **45.43s**，退出码 **Exit 0**，探针输出 `WIN_ARM64_OFFSCREEN_OK`，生成合法 Framebuffer；
  * **轮次 2（`--skip-draw` 真实负对照）**：耗时 **46.42s**，退出码 **Exit 21**，探针输出 `MISMATCH! Expected Triangle Color`，确证跳过绘制被捕获；
- **字节级完全回滚确证**：执行 `rollback` 后，目标工具目录被完整移除，无关标记文件完好保留，前后目录指纹（`fingerprint_pre.json` vs `fingerprint_post.json`）逐字节一致；
- **限定宿主观测确证**：核对 `~/Library/Application Support/Steam`、`~/Library/Application Support` 与 `/Applications`，实测顶层条目无任何名称增删（注：本检查证实顶层条目无名称增删，不泛化证明宿主系统全部文件内容零修改）。

---

## 6. 诊断门控限制与科学边界 (Caveats & Explicit Unknowns)

1. **CPU llvmpipe 软渲染声明**：
   - 本实验渲染由 Linux 客态下的 Mesa `llvmpipe (LLVM 23.1.1, 128 bits)` CPU 渲染器完成，**绝不宣称为宿主 Apple Silicon GPU 硬件加速**；
2. **诊断映射依赖声明**：
   - 本实验在 `ELFUSE_DIAG_SESSION_SHARED=1` 诊断映射环境下运行（该门控牺牲了 Linux 标准私有页 COW 隔离，仅用于跨进程 winstation 桌面共享同步）；
3. **显式未做项保持**：
   - 真实 Steam 客户端 GUI 启动、商业游戏 DRM、Metal 硬件加速后端及 x64/FEX 翻译维持 **`UNKNOWN`**。

---

## 7. 证据索引清册 (Evidence Manifest)

| 证据类别 | 物理文件路径 | 关键校验和 / 记录 | 说明 |
| :--- | :--- | :--- | :--- |
| **离屏执行收据** | `logs/vk-offscreen/receipt.json` | `status: COMPLETED` | 包含七层全状态判定与双轮耗时记录 |
| **像素采样结果** | `logs/vk-offscreen/pixel_verification.json` | 8 个采样点全部 MATCH | 内部 4 点全红，外部 4 点全蓝 |
| **合成负测试结果** | `logs/vk-offscreen/negative_tests.json` | `all_passed: true` | 防伪防 Clear 负测试通过 |
| **正常绘制标准输出** | `logs/vk-offscreen/stdout.log` | `WIN_ARM64_OFFSCREEN_OK` | 包含 10 个 Step 完整诊断日志 (Exit 0) |
| **负对照标准输出** | `logs/vk-offscreen/stdout_skip_draw.log` | `Exit 21 / MISMATCH` | 跳过绘制被探针捕获日志 |
| **原始 Framebuffer** | `logs/vk-offscreen/framebuffer.raw` | `2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050` | 16,384 字节原始像素数据 |
| **可视化渲染图** | `logs/vk-offscreen/framebuffer.png` | `311 bytes` | 64x64 RGBA 渲染图 |
| **无损放大渲染图** | `logs/vk-offscreen/framebuffer_256.png` | `1031 bytes` | 256x256 最近邻点对点无损放大图 |
| **安装前指纹** | `logs/vk-offscreen/fingerprint_pre.json` | - | 原始基准目录指纹 |
| **回滚后指纹** | `logs/vk-offscreen/fingerprint_post.json` | - | 逐字节完全对齐 |
| **ARM64 PE 探针** | `sources/vk-offscreen-probe/vk_offscreen_arm64.exe` | `112377ef135b5bb3d240646b665b1747bc21078ec8ee2272208bec2c1ae11e22` | 加固后离屏渲染测试探针 |
| **顶点着色器 SPV** | `sources/vk-offscreen-probe/shaders/triangle.vert.spv` | `e5170e632079a1770df89598258ef89570e397da3d533530fe559adb598e9b91` | 官方 spirv-val 校验通过 |
| **片段着色器 SPV** | `sources/vk-offscreen-probe/shaders/triangle.frag.spv` | `1a7ea883781c68884041cf223e181be962170bc784ff5d9df2d891e90eda4e36` | 官方 spirv-val 校验通过 |
| **自然对齐补丁库** | `sources/wine-pin-adea/target_patched_build/dlls/win32u/win32u.so` | `59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed` | 自然对齐 win32u 交付库 |
| **Shipped 原版库** | `fixtures/runtime/proton-derived/files/lib/wine/aarch64-unix/winevulkan.so` | `2786ca6f5f440821972e91a371e609d2d482597a8b6d75bcf02e287f83eea9ab` | Shipped 原版 Vulkan 库 |
| **全流程脚本** | `scripts/runtime/vk_offscreen/run_vk_offscreen.py` | - | 端到端完整可复现实测脚本 |
