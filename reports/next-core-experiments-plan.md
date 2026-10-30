# 下一阶段：正常映射语义与离屏绘制协同规划与收敛方案

用户已批准推进「正常 COW 映射语义」与「真实离屏绘制」两项核心攻坚任务。本文档记录两线并行规划、环境隔离约束、阶段性里程碑及最终收敛路径。

---

## 路线 A：关闭诊断共享映射 (Normal COW Mapping Line)
- **责任目标**：彻底消除 `ELFUSE_DIAG_SESSION_SHARED=1` 诊断映射，恢复 Linux 标准 `MAP_PRIVATE` 页缓存 Copy-On-Write (COW) 隔离语义；
- **核心任务**：
  1. 在独立派生 elfuse 与隔离测试根中复现普通 `MAP_PRIVATE` / `MAP_SHARED` 跨进程映射行为；
  2. 修复 winstation 会话对象在私有映射下的 cross-process 同步机制，杜绝盲目将 private 改 shared；
  3. 彻底在 `ELFUSE_DIAG_SESSION_SHARED=0`（或未设置）状态下消除 winstation 桌面锁死及 explorer 进程死循环；
- **验收标准**：映射回归测试通过、私写隔离测试通过、全套 backend 测试无倒退。

---

## 路线 B：真实离屏绘制与像素读回 (Real Offscreen Rendering Line - task-135 已达成)
- **责任目标**：实现 Windows ARM64 原生 PE Vulkan 图形管线真实绘制三角形与像素读回；
- **阶段性里程碑 (Milestone Achieved)**：**`WIN_ARM64_VULKAN_OFFSCREEN_PIPELINE_VERIFIED` (task-135 100% 达成)**：
  1. 编译并部署 Windows ARM64 PE 独立探针 `vk_offscreen_arm64.exe`（零 CRT 依赖，AArch64 PE32+，SHA256: `adda5e00...`）；
  2. 着色器源文件 `triangle.vert.spvasm` 与 `triangle.frag.spvasm` 经由官方 `spirv-as` 与 `spirv-val` 校验无误并直接嵌入；
  3. 真实录制并执行 `vkCmdDraw(vertexCount=3, instanceCount=1)` 绘制三角形至 64×64 RGBA8 离屏图像；
  4. 图像经管线屏障转入 Staging Buffer，栅栏等待（10s 超时保护）并由 CPU 内存映射读回 16,384 字节原始图像（SHA256: `2f69987b...`）；
  5. 8 个样点严格比对：内部 4 点全红 `(255, 0, 0, 255)`，外部 4 点全蓝 `(0, 0, 128, 255)` 100% 匹配；Pillow 成功输出可视化 `framebuffer.png`；
  6. 3 组 RED 负测试确证：跳过 Draw、颜色篡改及数据截断均被校验器 100% 拦截，杜绝纯 Clear 假阴性；
  7. 源目录移走后，由已安装 wrapper 独立拉起执行，耗时 44.12s 退出码 0，且字节级完全回滚对齐基准指纹；
  8. 完整收据归档于 `logs/vk-offscreen/receipt.json`，报告于 `reports/vk-offscreen.md`。

---

## 两线收敛方案 (Convergence & Hand-off Path)
1. **资源与环境严格隔离**：
   - 路线 A 与路线 B 运行在不同的测试 prefix 与日志目录下，互不抢占全局 Hypervisor 句柄与客态端口；
2. **阶段收敛接线**：
   - 当路线 A 在独立 elfuse 中成功实现关闭 `ELFUSE_DIAG_SESSION_SHARED=1` 且保持正常 winstation 映射后；
   - 直接将路线 B 现成验证通过的 `vk_offscreen_arm64.exe` 作为标准图形验收探针引入路线 A；
   - 在正常 COW 语义下复跑路线 B 的全量离屏绘制与像素校验流程；
   - 当探针在无诊断门控下同样输出 `FINAL_STATUS: WIN_ARM64_OFFSCREEN_OK` 且像素匹配时，两线达成最终完全收敛闭环。

---

## 边界红线提示
- 软渲染边界：设备始终为 `llvmpipe (LLVM 23.1.1, 128 bits)` CPU 渲染，绝不虚假宣称为宿主 Apple Silicon 硬件加速；
- 安全边界：严禁触碰真实 Steam 客户端目录，严禁提交任何临时 commit/push。
