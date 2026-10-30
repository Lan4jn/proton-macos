# HVF 只读宿主页映射探针与分类器安全加固独立复审报告

## 1. 复审背景与职责边界

- **复审目标**：对子任务卡（teammate: `subtask-0c89-644e2375` / 卡片 ID: `267d2efa-b5ba-4e53-a7d9-a023867122ea`）交付的 `hvf_readonly_probe` 安全加固改动进行独立工程复核与证据链校验。
- **职责边界规范**：
  - Lead 仅负责协调调度、静态 Diff 复审、纯测试（Pure Tests）独立执行复验、历史原件哈希核验与交付文档归档，**严禁替子卡编写实现代码**。
  - **原始实际运行绝对冻结**：严禁对宿主系统重新执行任何真实的 macOS HVF / Hypervisor API 物理注入调用，严禁启动任何 Wine / Guest 执行，严禁触碰任何全局或 Steam 系统组件，不执行 git commit / push。
  - **交付唯一性**：Lead 仅生成本复审报告 `reports/hvf-readonly-hardening-review.md`。

---

## 2. 缺陷修复与代码 Diff 复核

经 Lead 独立审查子卡在 `scripts/runtime/hvf_readonly_probe/` 目录下的代码改动，确认其针对原运行器的缺陷已完成精准加固：

### 2.1 既有种子文件防覆盖与 Fail-Closed 机制 (`run_probe.py`)
- **根除危险删除**：彻底删除了原 `run_probe.py` 第 50-53 行中对既有种子文件的 `path.unlink()` 逻辑，杜绝任何运行期主动删除或静默覆盖历史证据的行为。
- **预检阻断 (Fail-Closed)**：
  - 新增 `preflight_check_outputs()` 函数，在进入任何编译、代码签名或写入阶段前，对全部目标产物（`backing_seed.bin`、`probe` 二进制、`probe.jsonl`、`probe.log`、`hvf-readonly-probe.md`）调用 `os.path.lexists()` 扫描。
  - 一旦检测到任何历史产物已存在，立即触发 `[PREFLIGHT HALT]` 安全停止流程，绝不重跑编译、签名或探针。
- **严格符号链接与边界防御**：
  - 新增 `verify_path_boundary()` 函数，强制校验所有目标及其上级目录必须严格位于 `LAB_DIR` (`/Users/mewcapoo/Projects/proton-macos-lab`) 边界之内。
  - 显式拒绝目标本身或任意上级祖先路径为符号链接（包含悬空符号链接 Dangling Symlink），杜绝通过 Symlink 逃逸或覆盖任意系统文件的风险。
- **种子文件原子安全创建**：
  - `create_seed_file()` 严格限制底层文件创建标志为 `os.O_CREAT | os.O_EXCL | os.O_RDWR`（在支持平台上附加 `O_NOFOLLOW`）。
  - 循环完整写入 65536 字节并通过 `os.fsync(fd)` 保证物理刷盘，在 `try...finally` 块中强制 `os.close(fd)`，杜绝描述符泄露。

### 2.2 顶层最终判决强制绑定与分类器严格一致性 (`classifier.py`)
- **执行元数据强制绑定**：
  - `classify()` 顶层新增参数 `probe_returncode`、`timed_out`、`seed_sha_before`、`seed_sha_after`。
  - 凡 `timed_out is True`、`probe_returncode != 0` 或 `seed_sha_before != seed_sha_after`，直接阻断并裁决为 `INCONCLUSIVE`，不再允许非零退出或种子被修改的脏数据进入结论判定。
- **VM 生命周期与测试用例完整性及唯一性**：
  - 严格校验 `vm_create` 与 `vm_destroy` 事件的存在性与数值有效性，销毁失败判为 `CLEANUP_FAILURE`。
  - 强制要求 Case A、B、C、D 必须完整且唯一存在。一旦出现重复 Case ID（例如注入多个 Case B）或缺失用例，直接判定为 `INCONCLUSIVE`。
- **数值状态与布尔标志严格一致性**：
  - 校验 `hv_map_return == 0` 与 `hv_map_success is True` 对齐；`hv_unmap_return == 0` 与 `hv_unmap_success is True` 对齐。若出现数值与布尔标志冲突，判定为 `INCONCLUSIVE`。
- **根除伪 REJECTED 缺陷**：
  - 原分类器在 `else` 分支直接返回 `REJECTED`，导致 Case B 若因异常未调用 map 或字段为 None 时被误判为内核拒绝。加固后明确要求 Case B 必须具有合法的整型返回值与映射标志，否则统一判为 `INCONCLUSIVE`。
- **清理失败判定加固**：
  - 修正原逻辑中 `munmap_return` 为 None 时被误认为清理成功的漏洞；现强制要求 `munmap_return` 必须显式为整型 `0`，否则一律判定为 `CLEANUP_FAILURE`。

### 2.3 动态报告渲染与防 TypeError 字节解码 (`run_probe.py`)
- **动态报告生成**：移除了原报告中硬编码的“11 unit tests”及无条件“Controls succeeded”描述，依据实际单测数量及正对照实际状态动态生成 Markdown，行数严格控制在 $\le 12$ 行。
- **超时异常字节安全解码**：实现 `safe_decode()`，妥善处理 `subprocess.TimeoutExpired` 抛出时 `stdout`/`stderr` 可能为 `bytes` 的情况，彻底消除 `TypeError: can only concatenate str (not "bytes") to str`。

---

## 3. 构件哈希完整性审计（冻结 vs 新构件）

### 3.1 原始冻结构件 SHA-256（100% 冻结，未覆盖、未删除、未篡改）
Lead 独立对历史关键构件执行 `shasum -a 256` 校验，实测值与历史记录完全吻合：
| 冻结构件路径 | 记录 SHA-256 校验和 | Lead 独立实测 SHA-256 | 状态核验 |
| :--- | :--- | :--- | :--- |
| `scripts/runtime/hvf_readonly_probe/probe.c` | `eb7cd40a0a1e108734223d0b2d849ec5fdec3dbd1a655d196a2bd594bb52d81c` | `eb7cd40a0a1e108734223d0b2d849ec5fdec3dbd1a655d196a2bd594bb52d81c` | **MATCH (冻结)** |
| `fixtures/runtime/hvf-readonly-probe/probe` | `3694ff312e47ac9d92e7bb8e1909d9d45d4d8c5cefbcb7e1062d81b6270e42d3` | `3694ff312e47ac9d92e7bb8e1909d9d45d4d8c5cefbcb7e1062d81b6270e42d3` | **MATCH (冻结)** |
| `fixtures/runtime/hvf-readonly-probe/backing_seed.bin` | `1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de` | `1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de` | **MATCH (冻结)** |
| `logs/hvf-readonly-probe/probe.jsonl` | `ec90e845a5cdd97692b72c73edf1cc6fca18f9ec9937997968401e339b0f3311` | `ec90e845a5cdd97692b72c73edf1cc6fca18f9ec9937997968401e339b0f3311` | **MATCH (冻结)** |
| `logs/hvf-readonly-probe/probe.log` | `f6064aaca7c0bb525ca0b6c891e42d32de3b9f6c4c1a699f2f7436c89c4d3e98` | `f6064aaca7c0bb525ca0b6c891e42d32de3b9f6c4c1a699f2f7436c89c4d3e98` | **MATCH (冻结)** |
| `reports/hvf-readonly-probe.md` | `3d1e2792acb838f72eefe48dedf1d69d3e09d2db50a2fcc06de30d57ee15249a` | `3d1e2792acb838f72eefe48dedf1d69d3e09d2db50a2fcc06de30d57ee15249a` | **MATCH (冻结)** |

### 3.2 加固后工作代码新 SHA-256（真实演进，不伪称旧哈希）
| 工作代码路径 | 加固后新 SHA-256 校验和 | 变更说明 |
| :--- | :--- | :--- |
| `scripts/runtime/hvf_readonly_probe/run_probe.py` | `05cfc9e869fd0124fd41fb7124f0810105d49fd4c1741e66ddf63d095dda31d4` | 增加输出预检、O_EXCL种子创建、动态报告与 safe_decode |
| `scripts/runtime/hvf_readonly_probe/classifier.py` | `4242849bcd03b63fd722f8c73f48c18411758d63c3699290f130972a31622ac3` | 严格绑定执行状态、唯一Case校验、一致性与清理判定 |
| `scripts/runtime/hvf_readonly_probe/test_classifier.py` | `4bbda4b246777378592eccceffc19f306e2348a0156233ee3151ff46d2d080c3` | 新增边界异常单测至 21 项 |
| `scripts/runtime/hvf_readonly_probe/test_runner.py` | `ccd4771e1b212a473cb0b0b4f1b2aa374abdd295612e7783c96578d07e5157c5` | 新建隔离编排单测套件 11 项 |

---

## 4. 纯测试独立复验收据 (Pure Tests Ground Truth)

Lead 在工作目录内独立执行全部纯单元测试：
```bash
PYTHONPATH=scripts/runtime/hvf_readonly_probe python3 -m unittest discover -v -s scripts/runtime/hvf_readonly_probe -p "test_*.py"
```

### 4.1 测试执行结果
- **总测试数量**：**32 项纯单元与集成测试 100% 全部通过 (32/32 PASS, 0 failure, 0 error)**。
  - `test_classifier.py` (21 项)：覆盖 bytes 输入解析、VM 销毁失败、munmap 失败、unmap 失败、映射数值与布尔冲突、反向 unmap 冲突、重复 Case ID、提前中断、JSONL 解析、未调用 map 杜绝伪 REJECTED、缺失 Case、成功映射后缺少 unmap、缺失 munmap 严格判伪、非零退出码阻断、正对照 A 失败阻断、正对照 D 失败阻断、只读映射合法拒绝、只读映射准入、种子哈希不匹配阻断、进程超时阻断、VM 创建失败阻断。
  - `test_runner.py` (11 项)：覆盖悬空符号链接拒绝、非零退出码流程阻断、正常被拒离线重分类与动态报告输出、种子哈希篡改流程阻断、超时 bytes 流程阻断、超出 lab 边界路径拒绝、父级符号链接拒绝、已有输出存在预检阻断（compile/codesign/run 绝不触发）、O_EXCL 种子创建与 fsync、已有哨兵文件绝不删除、TimeoutExpired 字节解码防 TypeError。
- **环境隔离性核验**：
  - 测试临时目录严格限定于 `logs/hvf-readonly-hardening/test_fixtures/` 内，完全杜绝系统 `/tmp`。
  - 测试用例中对 `clang`、`codesign`、二进制执行均进行了 100% Mock 拦截。
  - **明确声明**：新增的所有错误分支均在纯 Mock 与内存结构中验证，**未发生任何针对真实 macOS HVF/Hypervisor 框架的物理注入执行**。

---

## 5. 离线重分类凭据与底层事实确认

使用加固后的 `ProbeClassifier` 对原始真实日志（`logs/hvf-readonly-probe/probe.jsonl`）进行离线重分类计算：
- **真实运行绑定凭证**：
  - 进程退出码：`probe_returncode = 0`
  - 进程超时标记：`timed_out = False`
  - 种子文件哈希：运行前后严格一致 (`1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de`)
- **实测底层数值事实**：
  - **Case A** (匿名 RWX 正对照): `hv_map_return = 0x0`, `hv_map_success = True`
  - **Case D** (文件 RWX 正对照): `hv_map_return = 0x0`, `hv_map_success = True`
  - **Case B** (文件 RO -> HV_R 目标组): `hv_map_return = 0xfae94001` (HV_ERROR), `hv_map_success = False`
  - **Case C** (文件 RO -> HV_RWX 对照组): `hv_map_return = 0xfae94001` (HV_ERROR), `hv_map_success = False`
- **重分类裁决结果**：
  - **Raw Verdict**: `REJECTED`
  - **Reason**: `RO_HOST_MAPPING_REJECTED (hv_return=0xfae94001)`
- **核心工程定性声明**：
  - 本实验现象仅代表 **Host API Admission 判定（macOS Hypervisor 内核接口在底层拒绝只读文件页建立 stage-2 内存映射）**。
  - 该结论仅为内核 stage-2 映射机制的物理边界测量，**绝非 Wine/Proton 用户态运行时的 Bug 修复**，不能推导或替代 Wine 共享内存映射机制。

---

## 6. 对前期报告 `reports/hvf-readonly-probe-review.md` 的追加纠正说明（不删历史）

前期报告 `reports/hvf-readonly-probe-review.md` 在当时的复审中，**过度肯定了初版 runner 编排器的完整性与健壮性**，存在以下未予指出的盲点与缺陷：
1. **忽略了不可覆盖保护缺失**：原运行器第 50-53 行无条件执行 `path.unlink()` 破坏了实验证据保护原则，前期报告未予纠正。
2. **忽略了执行元数据脱节风险**：原分类器未将进程退出码、超时标记、种子哈希校验与判决结果强绑定，存在非零退出或脏数据被误采信的潜在漏洞。
3. **忽略了报告硬编码**：原运行器硬编码了“11 unit tests”及无条件“Controls succeeded”，掩盖了动态测试覆盖度。
4. **忽略了清理状态误判**：原分类器将 `munmap_return is None` 视为成功清理，存在状态机漏洞。
5. **忽略了类型异常隐患**：原运行器未处理 `TimeoutExpired` 中 `bytes` 与字符串拼接问题。

**处理原则**：遵循项目审计规范，**原报告 `reports/hvf-readonly-probe-review.md` 全文完整保留，历史记录不作删除或回退篡改**；本报告在此作为正式勘误与增量补充，确立经过严格门控加固后的最终权威技术结论。

---

## 7. 任务看板状态与验收结论

- **子卡任务** (`267d2efa-b5ba-4e53-a7d9-a023867122ea` - “修复微探针不可覆盖与严格结果门控（仅纯测试）”)：
  - 交付物完备，32 项纯测试独立执行 100% PASS，哈希审计无误，缺陷全部修复且未破坏原始冻结资产。
  - **验收判定**：**复审通过 (PASSED)**。
- **任务看板同步说明**：
  - 子卡任务状态通过外部结果记录（`record-external-outcome`）归档为 `done`。
  - **Host 任务树全局状态声明**：鉴于部署环境中既有的 `session/follow` 历史拉取故障（`subagent Sessions require their durable parent address`），Lead **不虚假声称 Host 任务树全局 succeeded**，客观记录实际执行与卡片层级状态。
