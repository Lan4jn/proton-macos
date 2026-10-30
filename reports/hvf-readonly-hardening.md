# HVF 只读宿主页映射探针与分类器安全加固报告

## 1. 任务背景与加固范围
- **工作目录**：`/Users/mewcapoo/Projects/proton-macos-lab`
- **加固目标**：针对探针执行编排器 `run_probe.py`、分类器 `classifier.py` 以及测试套件中存在的覆盖写入、未绑定进程退出状态/超时/种子哈希、硬编码测试用例计数与正对照判定、字节类型串接异常等缺陷，完成全面安全防御加固。
- **加固代码范围**：
  - `scripts/runtime/hvf_readonly_probe/run_probe.py`
  - `scripts/runtime/hvf_readonly_probe/classifier.py`
  - `scripts/runtime/hvf_readonly_probe/test_classifier.py`
  - `scripts/runtime/hvf_readonly_probe/test_runner.py`（新编写测试运行套件）
- **冻结资产保护（完全未修改、未删除、未覆盖）**：
  - 源码：`scripts/runtime/hvf_readonly_probe/probe.c`
  - 二进制：`fixtures/runtime/hvf-readonly-probe/probe`
  - 种子文件：`fixtures/runtime/hvf-readonly-probe/backing_seed.bin`
  - 探针运行日志：`logs/hvf-readonly-probe/probe.jsonl`
  - 文本日志：`logs/hvf-readonly-probe/probe.log`
  - 原始报告：`reports/hvf-readonly-probe.md`
  - **声明**：冻结资产严格保留初始哈希，未重新编译、签名或对宿主 macOS HVF/Wine 发起新的物理注入运行。

---

## 2. 缺陷修复与安全加固实现

### 2.1 启动前输出保护与 Fail-Closed 机制 (`run_probe.py`)
- **不可覆盖与原子检查**：
  - 移除了原 `run_probe.py` 第 50-53 行中对既有种子文件的 `path.unlink()` 逻辑。
  - 新增 `preflight_check_outputs()`：在执行任何编译、签名或写入前，对所有预期产物（`backing_seed.bin`、`probe`、`probe.jsonl`、`probe.log`、`hvf-readonly-probe.md`）调用 `os.path.lexists()` 检查；若已有历史输出存在，立即停止流程（Halt Closed），绝不盲目重跑或覆盖。
- **符号链接与边界防御**：
  - 新增 `verify_path_boundary()`：严格验证目标路径及其所有祖先目录均位于 `LAB_DIR` 边界内，并禁止目标路径及其任意上级目录为符号链接（包含悬空符号链接 Dangling Symlink），杜绝路径遍历或链接注入。
- **种子文件安全创建**：
  - `create_seed_file()` 严格限制使用 `os.O_CREAT | os.O_EXCL | os.O_RDWR` 标志（在支持的平台附加 `O_NOFOLLOW`），循环完整写入 65536 字节并执行 `os.fsync(fd)`，在 `try...finally` 块中确保文件描述符正常关闭。

### 2.2 顶层最终判决绑定与分类器严格一致性 (`classifier.py`)
- **执行元数据强制绑定**：
  - `classify()` 顶层强制绑定 `probe_returncode == 0`、`timed_out == False`、`seed_sha_before == seed_sha_after`。任一条件不满足（非零退出码、进程超时、宿主种子被修改）立即判决为 `INCONCLUSIVE`。
- **完整 VM 生命周期校验**：
  - 严格校验 `vm_create` 与 `vm_destroy` 事件的存在性、返回值（`hv_return == 0`）与布尔标志（`success == True`）。创建失败判为 `INCONCLUSIVE`，销毁失败判为 `CLEANUP_FAILURE`。
- **测试用例唯一性与完整性**：
  - 强制要求 Case A、B、C、D 完整且唯一存在。出现重复 Case ID（例如多个 B）或缺失用例均直接判定为 `INCONCLUSIVE`。
- **数字状态码与布尔标志严格一致**：
  - 对每个用例的 `hv_map_return` 与 `hv_map_success`、`hv_unmap_return` 与 `hv_unmap_success` 进行逻辑对齐校验，禁止数字为 0 但 success=False 或数字非 0 但 success=True 的冲突状态。
- **杜绝伪 REJECTED 判决**：
  - 若 Case B 发生映射未调用、字段为 None、格式错误或未执行即中断，分类器判定为 `INCONCLUSIVE`，不再在 `else` 分支中盲目输出 `REJECTED`。
- **资源清理失败严格判定**：
  - 修正了原代码中 `c.get("munmap_return") not in (0, None)` 误将缺失 `munmap` 当作成功的缺陷。若 `munmap_return` 为 None、缺失或非 0，一律判定为 `CLEANUP_FAILURE`。

### 2.3 动态报告生成与字节安全解码 (`run_probe.py`)
- **报告动态化**：
  - 移除了原报告中硬编码的 `11 unit tests` 及无条件 `Controls succeeded`，根据实际传入的测试结果动态渲染正对照成功/失败描述与用例计数，维持输出不超过 12 行。
- **防 TypeError 字符串安全解码**：
  - 实现 `safe_decode()`，妥善处理 `subprocess.TimeoutExpired` 中捕获的 `bytes` 类型输出，杜绝字节串与文本拼接引起的 `TypeError`。

---

## 3. 构件哈希完整性审计

### 3.1 原始冻结构件 SHA-256（保持原件，未发生篡改）
| 构件路径 | SHA-256 校验和 | 状态 |
| :--- | :--- | :--- |
| `scripts/runtime/hvf_readonly_probe/probe.c` | `eb7cd40a0a1e108734223d0b2d849ec5fdec3dbd1a655d196a2bd594bb52d81c` | 冻结未动 |
| `fixtures/runtime/hvf-readonly-probe/probe` | `3694ff312e47ac9d92e7bb8e1909d9d45d4d8c5cefbcb7e1062d81b6270e42d3` | 冻结未动 |
| `fixtures/runtime/hvf-readonly-probe/backing_seed.bin` | `1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de` | 冻结未动 |
| `logs/hvf-readonly-probe/probe.jsonl` | `ec90e845a5cdd97692b72c73edf1cc6fca18f9ec9937997968401e339b0f3311` | 冻结未动 |
| `logs/hvf-readonly-probe/probe.log` | `f6064aaca7c0bb525ca0b6c891e42d32de3b9f6c4c1a699f2f7436c89c4d3e98` | 冻结未动 |
| `reports/hvf-readonly-probe.md` | `3d1e2792acb838f72eefe48dedf1d69d3e09d2db50a2fcc06de30d57ee15249a` | 冻结未动 |

### 3.2 加固后工作代码新 SHA-256（独立演进，不伪称同哈希）
| 工作代码路径 | 加固后新 SHA-256 校验和 | 说明 |
| :--- | :--- | :--- |
| `scripts/runtime/hvf_readonly_probe/run_probe.py` | `05cfc9e869fd0124fd41fb7124f0810105d49fd4c1741e66ddf63d095dda31d4` | 增加输出预检、O_EXCL种子创建、动态报告与safe_decode |
| `scripts/runtime/hvf_readonly_probe/classifier.py` | `4242849bcd03b63fd722f8c73f48c18411758d63c3699290f130972a31622ac3` | 严格绑定执行状态、唯一Case校验、一致性与清理判定 |
| `scripts/runtime/hvf_readonly_probe/test_classifier.py` | `4bbda4b246777378592eccceffc19f306e2348a0156233ee3151ff46d2d080c3` | 新增边界单测至 21 项 |
| `scripts/runtime/hvf_readonly_probe/test_runner.py` | `ccd4771e1b212a473cb0b0b4f1b2aa374abdd295612e7783c96578d07e5157c5` | 新建编排隔离单测 11 项 |

---

## 4. 纯测试验证收据（TDD: RED -> GREEN）

- **测试隔离环境**：所有测试临时文件均创建于 `logs/hvf-readonly-hardening/test_fixtures/` 内，严格禁止触碰系统 `/tmp`。
- **执行隔离保证**：所有编译器调用（`clang`）、代码签名（`codesign`）与二进制执行均为 Mock 拦截，未对真实 Hypervisor 或宿主内核执行物理注入。
- **测试通过情况**：
  - `test_classifier.py`: 21 / 21 PASS (覆盖退出码、超时、哈希不一致、重复 Case、未调用 map、缺失 munmap、冲突结果、bytes 输入)
  - `test_runner.py`: 11 / 11 PASS (覆盖哨兵不删除、悬空符号链接检测、上级符号链接拒绝、超出边界拒绝、O_EXCL 种子创建、bytes 超时解码、既有产物阻断、非零退出判决、超时判决、种子篡改判决、动态报告格式)
  - **总纯测试数量**：**32 个纯单元/集成测试 100% 通过**。

---

## 5. 离线重分类与最终结论

基于冻结的原运行收据（`logs/hvf-readonly-probe/probe.jsonl` 与 `logs/hvf-readonly-probe/probe.log`）进行纯离线重分类验证：
- **真实运行凭证**：
  - 进程退出码：`probe_returncode = 0`
  - 超时状态：`timed_out = False`
  - 种子哈希：运行前后一致 (`1fde717d808c7e06c2e08ea843c4c8214ba82e63ff07ab731a2da3bd489e15de`)
- **重分类判决结果**：
  - **Verdict**: `REJECTED`
  - **Reason**: `RO_HOST_MAPPING_REJECTED (hv_return=0xfae94001)`
  - **Details**: 正对照 Case A (匿名 RWX, `0x0`) 与 Case D (文件 RWX, `0x0`) 成功，Case B (文件 RO -> HV_R) 返回 `0xfae94001` (HV_ERROR)，映射清理及 VM 销毁全部完整。
- **收据存档路径**：
  - 结构化数据：`logs/hvf-readonly-hardening/reclassification.json`
  - 执行日志：`logs/hvf-readonly-hardening/hardening.log`
