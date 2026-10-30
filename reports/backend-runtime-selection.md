# 后端显式派生 elfuse 选择与运行时来源描述报告

**报告日期**：2026-10-15  
**执行角色**：`steam-probe-worker`（后端运行时选型实现员）  
**关联任务**：`task-23`（接入后端显式派生 elfuse 选择与来源描述）  
**实验根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**测试日志归档**：`logs/backend-runtime-selection/red.log`、`logs/backend-runtime-selection/green.log`  

---

## 一、 目标与设计原则

1. **显式覆盖与默认不变**：
   - 默认计划维持不变：未显式传递 `--elfuse` 时，默认使用原始上游干净构建 `sources/elfuse/build/elfuse`；
   - 显式覆盖：支持通过 `--elfuse <path>` 显式指定已验证的派生构建（例如三端已通过 minimal x64 exit 43 的 layout-only 派生包 `sources/elfuse-fex-derived/build/elfuse`，SHA-256：`0079fc5d9185103b1f1bccf0b22b712d6109f9ac19dc53de497a7b3e3bb60ba7`）；
   - 保持计划优先：默认仅输出结构化命令计划（`execution_performed: false`），不默认执行。

2. **来源描述符（Runtime Descriptor）**：
   - 在生成的执行计划及执行结果中增加 `runtime_descriptor`，包含：
     - `path`：解析后的真实绝对路径；
     - `sha256`：运行时的实际 SHA-256 校验和；
     - `flavor`：明确标定 `original` 或 `derived`；
     - `source_baseline`：严格依据 SHA-256 哈希匹配确定（如 `ORIGINAL_UPSTREAM_CLEAN`、`FEX_LAYOUT_ONLY_DERIVED`、`FUTEX_PATCHED_DERIVED`、`CUSTOM_UNVERIFIED_DERIVED`），拒绝仅凭文件路径或目录名猜测来源；
     - `commit`：真实 40-hex Git commit（原版及派生均锁定基于实测 `git -C sources/elfuse rev-parse HEAD` 得到的 `8612033dab8dc60728f604a4ea0441895fc16d39`）；
     - `patches`：补丁列表分字段标定（如 `['layout_shift', 'futex_wait_wake']` 或 `[]`），不把补丁标签拼接到伪 Git commit 中；
     - `description`：人工可读的来源说明；
     - `execution_evidence`：明确标定为 `NOT_CHECKED`，声明描述符属于静态检测，不将 plan/hash 冒充为运行时执行通过。

3. **安全边界与完整性校验**：
   - **Lab 本地隔离**：默认路径与显式参数均经过 `local()` 解析，杜绝符号链接逃逸，外部路径一律抛出 `ValueError` 并进入 `BLOCKED` 状态（Exit 20）；
   - **Mach-O 64-bit 深度校验**：
     - 文件大小必须 >= 32 字节（`mach_header_64` 结构体长度）；
     - 魔数必须为 `0xfeedfacf`（MH_MAGIC_64），FAT 通用二进制（`0xcafebabe`）明确作为不支持项阻断；
     - CPU 架构必须为 ARM64（`cputype == 0x0100000c`）；
     - 文件类型必须为可执行文件（`filetype == MH_EXECUTE (2)`）；
     - 校验加载命令区间边界（`file_size >= 32 + sizeofcmds` 且 `ncmds >= 1`），拒绝 4 字节虚假 magic 或损坏文件冒充；
     - 具备可执行权限（`os.access(p, os.X_OK)`）。

---

## 二、 代码实现改动

1. **`scripts/backend/bundle.py`**：
   - 引入 `struct` 解析 32 字节 `mach_header_64`，实现 `get_elfuse_descriptor(elfuse_path=None)`；
   - 默认路径经过 `local(LAB / 'sources/elfuse/build/elfuse')` 解析防逃逸；
   - 基于硬哈希查表判定基线并附加真实 40 位 commit 与 `patches`；
   - `build_plan` 新增向后兼容的可选参数 `elfuse_path=None`，注入 `runtime_descriptor`并在派生时在 `warnings` 中追加明确警告。

2. **`scripts/backend/cli.py`**：
   - 新增 `--elfuse` 命令行选项；
   - 将解析后的 `a.elfuse` 传递给 `build_plan`；执行完成后在输出 JSON 中保留 `runtime_descriptor`。

3. **测试套件与覆盖**：
   - `tests/backend/test_runtime_selection.py`（14 项单元测试）：覆盖默认原版、显式派生、外部路径逃逸拦截、缺失文件、非执行权限、非 Mach-O 拦截、4 字节假 magic 拦截、FAT 二进制拦截、非 ARM64/非 MH_EXECUTE 拦截、原路径替换二进制防伪造（哈希驱动）、commit/patches 字段验证及 CLI 退出码 20 验证。

---

## 三、 TDD 测试证据与全量验证

### 1. RED 阶段失败证据（`logs/backend-runtime-selection/red.log`）
在返工中新增针对 4 字节假 magic、FAT 二进制、非 MH_EXECUTE 以及 commit 验证的负例测试，真实捕获失败：
```text
FAIL: test_descriptor_records_commit_and_execution_evidence
FAIL: test_fat_cafebabe_rejected_as_unsupported
FAIL: test_non_arm64_or_non_execute_macho_rejected
FAIL: test_short_4byte_magic_only_rejected
FAILED (failures=4)
```

### 2. GREEN 阶段通过证据（`logs/backend-runtime-selection/green.log`）
修复 Mach-O 头校验与 commit 字段后，14 项单测全部通过：
```bash
python3 -m unittest tests/backend/test_runtime_selection.py -v
```

控制台实测回显：
```text
test_cli_blocked_elfuse_returns_exit_20 (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_cli_explicit_elfuse_plan_only (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_default_elfuse_is_original (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_descriptor_records_commit_and_execution_evidence (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_explicit_derived_elfuse_selection (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_explicit_futex_derived_selection (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_fat_cafebabe_rejected_as_unsupported (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_non_arm64_or_non_execute_macho_rejected (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_non_executable_elfuse_rejected (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_non_macho_elfuse_rejected (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_nonexistent_elfuse_rejected (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_outside_lab_elfuse_rejected (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_replaced_binary_at_original_path_marked_unverified (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok
test_short_4byte_magic_only_rejected (tests.backend.test_runtime_selection.TestRuntimeSelection) ... ok

----------------------------------------------------------------------
Ran 14 tests in 0.197s

OK
```
**退出码**：`0`。

### 3. 后端全量测试回归验证
执行完整的 `tests/backend` 测试套件（41 项全部通过）：
```bash
python3 -m unittest discover -s tests/backend -v
```
**结果**：`Ran 41 tests in 10.076s, OK`，41 项测试 100% 通过，退出码 0。

---

## 四、 交付文件清单

| 文件路径 | 状态 | 说明 |
| :--- | :---: | :--- |
| `scripts/backend/bundle.py` | 增强 | 新增 32 字节 Mach-O 校验与哈希基线提取 `get_elfuse_descriptor`，支持可选 `elfuse_path` 并输出带 commit/patches 的 `runtime_descriptor` |
| `scripts/backend/cli.py` | 增强 | 新增 `--elfuse` 选项并传递运行时描述符 |
| `tests/backend/test_runtime_selection.py` | 新增 | 14 项运行时选择、头校验、防伪造与描述符单元测试套件 |
| `logs/backend-runtime-selection/red.log` | 更新 | TDD RED 阶段原始失败记录 |
| `logs/backend-runtime-selection/green.log` | 更新 | TDD GREEN 阶段 14 项测试全量通过原始记录 |
| `reports/backend-runtime-selection.md` | 更新 | 本交付报告 |

---

## 五、 状态更新

- 任务 `task-23` 已全部完成，所有测试通过。
- 未修改 `process.py`/`supervisor.py`，未影响 `task-22` 代码，未触及原版包、真实 Steam 或系统全局设置。
