# 离线后端显式套接字隔离参数接入独立审查报告 (task-45)

**审查任务**：`task-45`（独立审查离线后端的显式 lab 套接字隔离参数）  
**审查角色**：`elfuse-baseline-worker`  
**被审对象**：task-44 在 `scripts/backend/` 及 `tests/backend/` 中的实现  
- `scripts/backend/bundle.py`（增加 `validate_absock_base`、descriptor capability、plan env 注入）  
- `scripts/backend/cli.py`（增加 `--absock-base` 命令行参数）  
- `scripts/backend/steam_handoff.py`（在准备候选与执行时支持 `absock_base` 校验与环境传递）  
- `tests/backend/test_absock_base.py`（新增 13 项自动化测试）  
**审查结论**：**APPROVED（验收通过）**  
- **核心判定**：代码严格遵循向后兼容与最小改动原则，默认 `absock_base=None` 对既有 50 项 backend 测试零破坏；显式 `--absock-base` 严格基于已知哈希（`06a2fceb...`）进行能力门禁，旧 runtime（`f2` 等）或未授权路径坚决拦截（`BLOCKED/exit 20`）；路径安全校验严格覆盖所有权、0700 权限、叶子符号链接（含尾随 `/`）、路径长度（`< 60` 字节 / 格式化 `≤ 72` 字节）；独立生成了 `artifacts/steam-prepared/socket-review-plan` 候选（`applied: false`, `execute_runtime: false`, mock 目标未落地）。全量 63 项后端测试及 12 项独立负例审查测试全数通过。

---

## 一、 核心安全与隔离门禁逐项核验

### 1. 默认行为与向后兼容（零回退保证）
- **核验事实**：当调用者未传 `--absock-base`（默认 `None`）时：
  - `build_plan()` 中 `validated_absock_base = None`，`plan['env']` 中**绝不注入 `ELFUSE_ABSOCK_BASE`**；
  - 既有 `tests/backend/` 全部 50 项测试（包括 `test_bundle.py`, `test_process.py`, `test_runtime_selection.py`, `test_steam_handoff.py` 等）100% 保持原始行为通过；
  - 既有离线 Steam prepared 候选包不受任何干扰。

### 2. 基于哈希的严格能力门禁 (Hash-Based Capability Gating)
- **代码位置**：`scripts/backend/bundle.py:218-226` 与 `steam_handoff.py:87-92`
  ```python
  if absock_base is not None:
      if not descriptor.get('capabilities', {}).get('supports_absock_base'):
          return {
              'status': 'BLOCKED',
              'reason': f"Runtime {descriptor.get('source_baseline')} does not have supports_absock_base capability; explicit absock_base requires socket-derived elfuse (06a2fceb...)",
              'execution_performed': False,
          }
  ```
- **实测断言**：
  - 仅当 runtime 的 descriptor 具备 `capabilities.supports_absock_base = True`（即绑定已验收的 `sources/elfuse-socket-derived/build/elfuse` 哈希 `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`）时放行；
  - 若调用者显式传入 `--absock-base` 但选择旧 `f2`（`sources/elfuse-lifecycle-derived`）、原始 upstream、FEX layout 派生或任意未知 runtime，立即返回 `BLOCKED` 并以退出码 `20` 拒绝，**坚决不忽略参数，绝不允许回退至宿主 `/tmp`**。

### 3. `validate_absock_base` 路径安全与边界深度校验
- **代码位置**：`scripts/backend/bundle.py:54-115`
- **核验断言矩阵**（经 12 项独立负例测试 `logs/socket-backend-review/run_review_verification.py` 验证）：
  1. **空值与点拦截**：`""`, `"   "`, `"."` 立即抛出 `ValueError`；
  2. **绝对路径强制要求**：相对路径（如 `.s`, `./.s`, `relative/path`）在进入解析前即被拦截（`if not raw_p.is_absolute(): raise ValueError(...)`）；
  3. **LAB 目录封闭性**：路径必须在当前实验根目录内部（`resolved_p.is_relative_to(LAB)`），外部路径（如 `/tmp`, `/tmp/.s`, `/Users/mewcapoo`）全部拦截；
  4. **真实存在性与目录类型**：必须真实存在且必须为普通目录（文件或不存在路径立即报错）；
  5. **所有权严格校验**：`st.st_uid == os.getuid()`，非当前用户拥有的目录坚决拒绝；
  6. **权限严格为 0700**：`stat.S_IMODE(st.st_mode) == 0o700`，任何带组读写或全局读写的权限（`0755`, `0777`, `0750`, `0711`）全部拒绝；
  7. **叶子符号链接与尾随斜杠防御**：
     - 在执行 `resolve()` 前，先使用 `os.lstat(raw_p)` 检测原始叶子；
     - 针对带有尾随斜杠的路径（如 `/path/to/link/`，部分 OS 的 `lstat` 会跟随软链接），先执行 `raw_str.rstrip('/')` 规整再执行 `lstat`，确保叶子符号链接无所遁形（`if stat.S_ISLNK(raw_st.st_mode): raise ValueError(...)`）；
  8. **C 缓冲区长度预算检查**：
     - 使用 `encoded = os.fsencode(canonical_str)` 严格按 UTF-8 字节数计算长度（而非字符数）；
     - 要求 `len(encoded) < 60` 字节；
     - 校验格式化输出预算 `len(encoded) + 18 <= 72` 字节（对应 C 源码 `snprintf(out, out_sz, "%s/n%016llx", clean_base, namespace_id)` 的 72 字节上限）。

### 4. 计划阶段零副作用 (Plan-Only Purity)
- **核验事实**：
  - 构造计划阶段（`build_plan` 或 `prepare_runtime_tool`）若目标 base 不存在，立即失败拦截，**绝不自动 `mkdir` 创建缺失目录**；
  - 整个准备阶段不启动任何外部进程（`execution_performed = False`），不调用 Wine，不侵入系统。

### 5. 环境变量传递通路 (Native Extra Env)
- **代码位置**：`scripts/backend/bundle.py:249-250`
  ```python
  if validated_absock_base:
      env['ELFUSE_ABSOCK_BASE'] = validated_absock_base
  ```
- **核验事实**：
  - `ELFUSE_ABSOCK_BASE` 作为 native 运行环境注入到 `plan['env']` 中；
  - 当通过 `run_isolated(plan['argv'], ..., extra_env=env)` 执行时，该变量作为宿主 native 环境变量传给 `elfuse`，能够被 `sources/elfuse-socket-derived/src/syscall/net-absock.c` 直接读取；
  - 绝不使用仅在 guest user-space 生效的 `--env` 伪装传递。

### 6. 描述符与来源追踪真实性 (Descriptor Provenance Fidelity)
- **代码位置**：`scripts/backend/bundle.py:35-43`
  ```python
  '06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d': {
      'flavor': 'derived',
      'source_baseline': 'SOCKET_DERIVED',
      'commit': '8612033dab8dc60728f604a4ea0441895fc16d39',
      'patches': ['layout_shift', 'futex_wait_wake', 'preempt_lifecycle_stop_join', 'absock_custom_base'],
      'description': 'Derived elfuse with lifecycle stop/join and explicit lab-only absock base relay',
      'capabilities': {'supports_absock_base': True},
  }
  ```
- **核验事实**：
  - 严格记录上游锁定 Commit `8612033dab...` 及派生包含的 4 项 patch；
  - 描述符在计划中声明 `execution_evidence: NOT_CHECKED`，绝不因配置了正确哈希就虚假宣称执行层通过。

### 7. Hand-off 运行时二次校验与参数保真
- **代码位置**：`scripts/backend/steam_handoff.py:108` 与 `steam_handoff.py:232`
- **核验事实**：
  - 准备阶段在 `config.json` 中持久化记录 `absock_base`；
  - 执行阶段（`execute_from_config`）重新调用 `build_plan`，再次触发 `validate_absock_base`，若准备之后目录被删除、替换为软链接或修改为非 0700 权限，执行将被坚决阻断（返回退出码 `20`）；
  - 维持原有 `shlex.quote` 与参数解析逻辑，任意带有 Unicode、空格、百分号、特殊元字符的 argv 原样保留不展开。

---

## 二、 独立候选生成与验证 (`socket-review-plan`)

本审查员在独立目录中通过代码生成并验证了离线 Steam 候选套件：
- **候选输出路径**：`/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/socket-review-plan`
- **Mock 目标路径**：`/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/mock-target-absent`
- **生成结果元数据**：
  ```json
  {
    "candidate": "/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/socket-review-plan",
    "target": "/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/mock-target-absent/proton-macos-lab-runtime",
    "applied": false,
    "execute_runtime": false,
    "purpose": "Offline Steam-shaped runtime candidate handoff",
    "elfuse_candidate": "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-socket-derived/build/elfuse",
    "elfuse_sha256": "06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d",
    "sysroot": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "linux_python": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14",
    "compat_prefix": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/steam-shaped/compat/pfx"
  }
  ```
- **实测断言全部满足**：
  - `install-plan.json` 中 `applied == false`；
  - `execute_runtime == false`（默认纯计划模式）；
  - `config.json` 中 `absock_base == "/Users/mewcapoo/Projects/proton-macos-lab/.s"`；
  - `mock-target-absent` 目录在宿主磁盘上**绝对不存在（未落地，零污染）**。

---

## 三、 边界限制声明：Directory Inode Swap

依据 Team Lead 审查备忘，在此对目录篡改防御边界作诚实声明：
- **当前防护范围**：`steam_handoff.py` 在执行前重新对 `absock_base` 执行 `validate_absock_base`，能够完全拦截“目录被篡改为软链接”、“目录权限被放宽至非 0700”、“目录被移出 LAB”以及“目录被删除”。
- **未覆盖边界 (Directory Inode Swap)**：
  如果外部进程在准备和执行之间将 `lab/.s` 目录删除，并重新创建了一个同名、同用户所有、权限同样为 `0700` 的新目录（即仅替换了底层文件系统的 `inode`），当前配置仅记录了路径字符串，未持久化 `(st_dev, st_ino)` 元组，因此会认为其依然合法。在此如实记录：**同属主、同权限的同名目录 Inode 替换属于未验证/未封锁边界**，后续若有更深层防伪需求可在 `config.json` 中增加 `(st_dev, st_ino)` 校验。

---

## 四、 测试数据汇总

1. **后端完整测试套件 (`tests/backend/`)**:
   - `python3 -m unittest discover -s tests/backend -p "test_*.py"`
   - **实测结果**：`Ran 63 tests in 5.702s, OK (exit 0)`
   - 包含新增的 13 项 `test_absock_base.py` 自动化测试。
2. **独立审查负例套件 (`logs/socket-backend-review/run_review_verification.py`)**:
   - 包含 12 项针对非法路径、相对路径、越界路径、文件替换、软链接（带/不带 `/`）、非 0700 权限、超长路径、旧 runtime 拒绝、无副作用验证的独立测试。
   - **实测结果**：`Ran 12 tests in 0.009s, OK (exit 0)`
   - 日志已固化于 `logs/socket-backend-review/review_verification.log`。

---

## 五、 交付产物汇总

- **独立审查报告**：`/Users/mewcapoo/Projects/proton-macos-lab/reports/socket-backend-review.md`
- **独立验证日志**：`/Users/mewcapoo/Projects/proton-macos-lab/logs/socket-backend-review/review_verification.log`
- **独立测试脚本**：`/Users/mewcapoo/Projects/proton-macos-lab/logs/socket-backend-review/run_review_verification.py`
- **独立生成的候选计划**：`/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/socket-review-plan/`

综上，task-44 实现完备合规，本审查正式通过，`task-45` 置为 `completed`。
