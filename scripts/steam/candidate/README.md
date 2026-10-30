# Steam 兼容工具离线 Candidate VDF 规范与离线样例说明

> **安全与隔离铁律**：本目录下的所有文件均为**离线研究与分析样例**，**绝不复制到宿主 Steam 目录**（如 `~/Library/Application Support/Steam/compatibilitytools.d/`），**绝不修改系统与 Steam 客户端配置**。

---

## 1. 规范来源与接口参考

本候选模板严格参照 Valve 官方公开文档与开源实现：
1. **Steam 兼容工具接口规范**：[Valve steam-compat-tool-interface.md](https://gitlab.steamos.cloud/steamrt/steam-runtime-tools/-/blob/main/docs/steam-compat-tool-interface.md)
   - 规定了工具目录结构、`compatibilitytool.vdf` 元数据注册、`toolmanifest.vdf` 启动清单格式及接口版本号（Interface Version 1 与 Version 2）。
2. **Valve Proton 官方仓库**：[ValveSoftware/Proton](https://github.com/ValveSoftware/Proton)
   - `compatibilitytool.vdf.template` 定义了 `from_oslist`（目标游戏操作系统，如 `windows`）与 `to_oslist`（宿主运行环境）。

---

## 2. 核心阶段隔离（三阶段不可混淆）

在评估 macOS Steam 对兼容工具的适配时，必须严格区分以下三个完全独立的阶段，不能把前一阶段的成功臆断为后续阶段通过：

1. **第一阶段：Manifest 发现（Discovery）**
   - Steam 客户端启动时遍历 `compatibilitytools.d/`，读取 `compatibilitytool.vdf`。
   - 仅代表客户端解析了 VDF 文本，将其作为注册项存入内存数据结构。
2. **第二阶段：列表可选（UI Dropdown Selectable）**
   - 在 Steam 设置「兼容性」（Steam Play）或具体游戏的「属性 → 兼容性」下拉列表中，该工具是否展示并允许用户勾选。
   - **注意**：macOS 客户端原生未开放针对 Windows-only 游戏的通用 Proton 选项，即使 VDF 语法通过发现，UI 依然可能因平台过滤策略而不予展示。
3. **第三阶段：Play 实际调度与调用（Play Invocation）**
   - 用户点击「开始游戏（Play）」按钮后，Steam 读取 `toolmanifest.vdf` 的 `commandline`，注入 `STEAM_COMPAT_*` 环境变量并以 `waitforexitandrun <game_path>` 调用包装脚本。
   - **注意**：脚本进程被调用仅说明拉起成功，并不等同于 Windows 游戏成功运行，更不等同于 Steamworks API、DRM、IPC 与云存档通过。

---

## 3. `to_oslist "macos"` 并非功能承诺

Valve 接口文档中允许在 `to_oslist` 中声明目标操作系统名称（如 `linux`, `windows`, `macos`）。但必须明确：
- **`to_oslist "macos"` 仅为元数据语法字段**，并不代表 Valve 官方对 macOS Steam 客户端做出了任何功能承诺或技术保证。
- 官方 macOS Steam 客户端目前并未正式启用 Linux 式的 Steam Play / Proton 运行时重定向。

---

## 4. 社区历史先验辨析（Kaon 路径与假设说明）

社区项目（如 `natbro/kaon` 2025-02-15 记录）曾探索在 macOS 上挂载包装器：
- **拼写与路径纠偏**：Kaon 等历史记录在文档中存在路径拼写错误与非标准目录命名（如对 `compatibilitytools.d` 路径大小写或层级的混淆）。本实验严格以 Valve 官方 `steam-compat-tool-interface.md` 为权威基准，不盲从历史笔误。
- **未验证机制**：社区提出的 `steam_dev.cfg` 绕过、`appinfo.vdf` 重定向包装、Wine 内运行 Windows Steam 接管 Steamworks 等设想，在当前最新版 macOS Steam 客户端中均**未经实机验证**。
- 本项目严禁把社区未经证实的临时 trick 伪装成可直接安装的成熟方案。

---

## 5. 候选模板与生成工具

- `compatibilitytool.vdf.template`：元数据注册模板。
- `toolmanifest.vdf.template`：执行清单模板。
- `generate_candidate.py`：本地样例生成脚本。该脚本基于当前环境真实绝对路径（`probe.py` 与 `logs/steam`）生成具体的 `compatibilitytool.vdf` 与 `toolmanifest.vdf`，不依赖虚构环境变量或占位符，仅供离线静态审查。

### 5.1 命令格式 `-- %verb%` 规范说明
在 `toolmanifest.vdf` 中，`commandline` 采用如下标准格式：
```vdf
"commandline" "/path/to/python3 /path/to/probe.py --log-dir /path/to/logs -- %verb%"
```
- **保留 Steam 调度动词**：当 Steam 客户端拉起工具时，会将 `%verb%` 替换为实际动词（如 `waitforexitandrun` 或 `run`）及游戏可执行路径与后续参数。
- **防止游戏参数污染探针**：`--` 放置在 `--log-dir` 之后、`%verb%` 之前。探针 CLI 解析器在遇到 `--` 时立即终止内部选项提取，确保 `%verb%` 动词作为 `argv[0]` 被完整记录，同时防止游戏自身的 `--log-dir` 参数被探针错误吞噬。
- **空格与引号转义**：生成器内置 `format_vdf_arg`，当路径中包含空格或引号时自动添加转义引号 `\"...\"`，确保跨平台解析的一致性。
- **Python 运行时声明**：生成样例使用当前 Python 解释器绝对路径（`sys.executable`），保留本机环境真实依赖，不作无法验证的跨机假设。
