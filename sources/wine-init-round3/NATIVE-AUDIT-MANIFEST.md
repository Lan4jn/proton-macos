# Round 3 Combined Native Audit 审计与既有依赖关联清单 (NATIVE-AUDIT-MANIFEST.md)

## 1. 架构与审计范围声明
- **审计目标**：核实 `task-22` 补充的 6 项 PE 核心库在 Wine Unix 端的底层关联依赖，确证是否存在新增的 Linux 动态链接库缺项；
- **核心结论**：
  - 6 项 PE 核心库中，仅 `win32u.dll` 存在 Unix-side 对等组件 `win32u.so`；
  - 该文件在原包 `sources/proton-v3-deploy/original/files/lib/wine/aarch64-unix/win32u.so` 中**已作为物理常规文件存在**（SHA256: `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5`，大小 2,380,512 字节）；
  - `win32u.so` 的 ELF `DT_NEEDED` 依赖仅包含 `ntdll.so`, `libm.so.6`, `libc.so.6`，在现有的基础 sysroot 与 3 项 FEX Unix 库部署后已完全满足，**无新增 Unix 动态库需求**；
  - 动态字体引擎（如 `libfreetype.so`, `libfontconfig.so`）属于动态探测软依赖，源码具备 fallback 路径，不作为本次 Wineboot 初始化的硬阻断项。

---

## 2. 既有依赖项与排除项记录（预算透明声明）

为保持已审定的 27 源闭包清单（[CLOSURE_MANIFEST_R3_COMBINED.json](<CLOSURE_MANIFEST_R3_COMBINED.json>)）的 100% 不变性，`win32u.so` 作为原包中既已存在的固有组件进行单独归档记录，**不计入 27 项新增逻辑源预算（不重复占额）**：

| 组件名称 | 原始源文件物理路径 | 部署目标路径 (target_root 内部) | 物理字节大小 | SHA256 哈希 | 属性与定性 |
|---|---|---|---|---|---|
| `win32u.so` | `sources/proton-v3-deploy/original/files/lib/wine/aarch64-unix/win32u.so` | `wine/lib/wine/aarch64-unix/win32u.so` | 2,380,512 字节 (~2.27 MiB) | `4f6013fa6f8a9a4356d6342b1f49f245354f18dfb896b662cdc502df8f803fb5` | 原包既有组件 (Physical File, 非断链) |

- **部署完整性保证**：
  在 `wine_diagnostics_launcher_v4_combined.py` 构建 target root 时，由于底层调用了 `wine_launcher.py:clone_or_copy` 全量 APFS clonefile 复制 `sources/proton-v3-deploy/original/files` 至 `target_root/wine/`，`win32u.so` 确已在 `target_root/wine/lib/wine/aarch64-unix/win32u.so` 处落地为完整可执行文件（其目标哈希 100% 严格匹配 `4f6013fa...`），绝非 broken 软链接！

---

## 3. 阶段准入状态
- 本说明书已完成对齐并落盘，**当前未运行真实 Wine，未持锁**；
- 保持已通过测试的 `wine_diagnostics_launcher_v4_combined.py` (SHA `ee356252...`) 冻结不变；
- 提交审查员独立终审，等待 Lead 下发下一执行锁 `wine-init-r3-combined-01`。
