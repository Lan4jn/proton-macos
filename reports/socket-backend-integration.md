# 显式 Lab 套接字隔离参数接入离线 Steam 后端实测报告 (task-44)

**实验日期**：2026-10-16  
**执行员**：`proton-package-worker`  
**关联任务**：`task-44`（将显式 lab 套接字隔离参数接入离线 Steam 后端）  
**宿主环境**：Apple Silicon macOS 27.0.1 (Build 26A434, arm64, Rosetta 2 可用, 磁盘可用空间 246 GiB)  
**交付物路径**：
- 后端计划构建与校验核心：`scripts/backend/bundle.py`
- 后端 CLI 接口：`scripts/backend/cli.py`
- Steam-shaped 准备器与执行器：`scripts/backend/steam_handoff.py`
- 专属测试套件：`tests/backend/test_absock_base.py` (13 项测试全绿)
- 全量后端测试套件：`tests/backend/` (共 63 项测试全绿)
- 新准备产物候选（仅计划、未安装、未执行）：`artifacts/steam-prepared/socket-plan-only/`
- 真实执行与验证日志：`logs/socket-backend-integration/`
  - `prepare_stdout.json` (准备命令输出)
  - `plan_run_stdout.json` (包装器 plan-only 实测输出，验证 native `ELFUSE_ABSOCK_BASE` 注入)

---

## 1. 核心目标与执行摘要 (Executive Summary)

1. **显式套接字基址能力（`supports_absock_base`）严格基于哈希判定**：
   - 在 `scripts/backend/bundle.py` 的 `KNOWN_ELFUSE_BASELINES` 中注册已由 task-40/41 验证的 socket-derived 运行时：
     - **路径**：`sources/elfuse-socket-derived/build/elfuse`
     - **SHA-256**：`06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`
     - **来源基线**：`ABSOCK_CUSTOM_BASE_DERIVED` (基于 pinned commit `8612033dab8dc60728f604a4ea0441895fc16d39`)
     - **派生补丁清单**：`['layout_shift', 'futex_wait_wake', 'preempt_lifecycle_stop_join', 'absock_custom_base']`
     - **显式能力标记**：`capabilities: {"supports_absock_base": True}`
     - **执行证据保持**：`execution_evidence: "NOT_CHECKED"`（不凭哈希冒充 Wine 执行成功）
   - **严格防回退与拒载逻辑**：
     - 当显式传入 `--absock-base` 时，后端严格校验 `runtime_descriptor['capabilities']['supports_absock_base'] == True`。
     - 若使用旧候选（f834...）、旧 lifecycle（f2a6...）、原始上游（dd5d...）或未经验证的自定义构建，**直接返回 `status: BLOCKED` 并退出码 20**，绝不静默忽略该参数回退至宿主 `/tmp`。
2. **多重安全防护与路径验证 (`validate_absock_base`)**：
   - **Lab 作用域**：路径必须在 `LAB` 根目录下，严格拒绝相对路径（必须是显式绝对路径）与越界路径。
   - **解析前软链接检查**：在执行 `resolve()` 之前先以原始路径去除尾随斜杠后执行 `lstat`，**严格拒绝叶子节点为软链接（含带尾随斜杠的情形）**，防止符号链接欺骗。
   - **文件状态与权限**：必须已存在且为真实目录（计划阶段绝不自动创建缺失目录）；所有者必须为当前运行用户（`st.st_uid == os.getuid()`）；权限模式必须严格为 `0700`（禁止 group/others 权限）。
   - **C 语言缓冲区字节级预算**：UTF-8 编码字节数 `len(os.fsencode(clean_base)) < 60` 字节，且格式化预留 `clean_base + 18 <= 72` 字节（对应 C 源码 snprintf 格式 `"%s/n%016llx"` 与 72 字节上限）。
3. **Steam-shaped 准备器与执行重检 (`steam_handoff.py`)**：
   - `prepare_runtime_tool` 接收可选参数 `absock_base`，存入生成的 `config.json`。
   - **执行阶段重检**：在 `execute_from_config` 时，再次调用 `build_plan` 及其内部的 `validate_absock_base`，若准备后目录被篡改（如权限放宽为 0755、被替换为软链接），**执行立即被阻断（`status: BLOCKED`, exit 20）**。
   - **Native 环境变量传递**：`ELFUSE_ABSOCK_BASE` 注入至 `plan['env']`，由 `scripts.backend.process.run_isolated` 作为 native extra_env 传递给宿主 elfuse 进程，而不是作为仅在 guest 生效的参数。
4. **全套回归与 Plan-only 候选生成**：
   - 现有 50 项 backend 测试零破坏，新增 13 项专属测试，全量 63 项测试 100% PASS。
   - 生成全新候选 `artifacts/steam-prepared/socket-plan-only`：`applied: false`，`execute_runtime: false`，target 明确为未创建的 mock 路径，未调用真实 Wine 进程（不与 task-42 并发冲突）。

---

## 2. 核心代码变更清单

### 2.1 `scripts/backend/bundle.py`
1. 注册 socket-derived 哈希 `06a2fceb...`，标注 `capabilities: {"supports_absock_base": True}`。
2. 引入 `import stat`，实现纯标准库函数 `validate_absock_base(base_path) -> str`：
   - 拒绝空字符串、点号 `.` 以及相对路径；
   - 解析前 `lstat` 去除尾随斜杠的路径，拒绝 `S_ISLNK`；
   - 检验 `is_relative_to(LAB)`、`is_dir()`、`st_uid == os.getuid()`、`mode == 0o700`；
   - 检验 UTF-8 编码字节数 `< 60` 且 `+ 18 <= 72`。
3. `build_plan` 新增 `absock_base=None` 参数：
   - 显式传入时检查 `descriptor['capabilities']['supports_absock_base']`，不满足返回 `status: BLOCKED`；
   - 验证通过后写入 `env['ELFUSE_ABSOCK_BASE']` 并记录在计划中。

### 2.2 `scripts/backend/cli.py`
- 新增可选参数 `--absock-base`（类型 `Path`，默认 `None`）。
- 将参数传递给 `build_plan(..., absock_base=a.absock_base)`，阻断时返回 exit 20。

### 2.3 `scripts/backend/steam_handoff.py`
- `prepare_runtime_tool` 新增 `absock_base=None` 参数，在准备阶段完成能力与路径安全前置校验，并记录到候选 `config.json` 的 `"absock_base"` 字段。
- CLI 新增 `--absock-base` 命令行参数。
- `execute_from_config` 读取 `cfg.get("absock_base")` 并传给 `build_plan`，在执行前完成第二次动态安全核验。

---

## 3. 自动化测试套件与执行证据 (`tests/backend/test_absock_base.py`)

编写了 13 项全面覆盖的测试用例：
```bash
$ python3 -m unittest tests/backend/test_absock_base.py -v
test_default_plan_has_no_absock_base_env ... ok
test_explicit_base_rejected_on_unsupported_runtimes ... ok
test_steam_handoff_execute_revalidates_absock_base ... ok
test_steam_handoff_prepare_absock_base_plan_only ... ok
test_valid_explicit_base_with_socket_derived_elfuse ... ok
test_validate_absock_base_bad_permissions_rejected ... ok
test_validate_absock_base_file_rejected ... ok
test_validate_absock_base_length_limit ... ok
test_validate_absock_base_nonexistent_rejected ... ok
test_validate_absock_base_outside_lab_rejected ... ok
test_validate_absock_base_symlink_leaf_rejected ... ok
test_validate_absock_base_symlink_with_trailing_slash_rejected ... ok
test_validate_absock_base_unicode_byte_length ... ok

----------------------------------------------------------------------
Ran 13 tests in 0.084s

OK
```

全量后端测试套件回归验证：
```bash
$ python3 -m unittest discover -s tests/backend -v
# 运行 63 项测试（含 test_absock_base 13 项，test_steam_handoff 8 项，test_runtime_selection 14 项，test_process 15 项，test_bundle 7 项，test_regressions 3 项，test_prepare_integration 2 项，test_pattern_classifier 1 项）
Ran 63 tests in 5.743s

OK
```
全套 63 项测试全量通过，无任何回归或跳过用例。

---

## 4. 离线 Steam 候选产物实证 (`artifacts/steam-prepared/socket-plan-only`)

### 4.1 生成命令与安装计划
```bash
python3 scripts/backend/steam_handoff.py \
    --prepare artifacts/steam-prepared/socket-plan-only \
    --target /Users/mewcapoo/Projects/proton-macos-lab/mock-steam/compatibilitytools.d \
    --elfuse sources/elfuse-socket-derived/build/elfuse \
    --absock-base /Users/mewcapoo/Projects/proton-macos-lab/.s
```

输出 `install-plan.json`：
```json
{
  "candidate": "/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/socket-plan-only",
  "target": "/Users/mewcapoo/Projects/proton-macos-lab/mock-steam/compatibilitytools.d/proton-macos-lab-runtime",
  "applied": false,
  "execute_runtime": false,
  "purpose": "Offline Steam-shaped runtime candidate handoff",
  "elfuse_candidate": "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-socket-derived/build/elfuse",
  "elfuse_sha256": "06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d",
  "sysroot": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
  "linux_python": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14",
  "compat_prefix": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/steam-shaped/compat/pfx",
  "backup": "Before any future install, preserve an existing target directory under a unique backup name.",
  "rollback": "Remove only the installed candidate directory after identity verification, then restore backup. No install has run."
}
```

### 4.2 包装器 Plan-only 模式实测 (`logs/socket-backend-integration/plan_run_stdout.json`)
运行 `./artifacts/steam-prepared/socket-plan-only/proton-wrapper.sh runinprefix "C:\hello-x64.exe"`：
```json
{
  "status": "PLAN_READY",
  "argv": [
    "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-socket-derived/build/elfuse",
    "--user",
    "501:20",
    "--sysroot",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case",
    "--timeout",
    "90",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/usr/bin/python3.14",
    "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/proton",
    "runinprefix",
    "C:\\hello-x64.exe"
  ],
  "env": {
    "WINEPREFIX": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/steam-shaped/compat/pfx",
    "WINEESYNC": "0",
    "WINEFSYNC": "0",
    "WINEDEBUG": "-all",
    "PROTON_NO_ESYNC": "1",
    "PROTON_NO_FSYNC": "1",
    "PROTON_NO_NTSYNC": "1",
    "WINESERVER": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wineserver",
    "WINELOADER": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/proton-derived/files/bin-arm64/wine",
    "ELFUSE_ABSOCK_BASE": "/Users/mewcapoo/Projects/proton-macos-lab/.s",
    "STEAM_COMPAT_DATA_PATH": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/steam-shaped/compat",
    "STEAM_COMPAT_CLIENT_INSTALL_PATH": "/Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/steam-stub"
  },
  "engine": "proton",
  "warnings": [
    "Publisher checksums verified; Valve signature was not independently verified.",
    "A command plan is not evidence of successful Windows execution.",
    "Using derived elfuse runtime (ABSOCK_CUSTOM_BASE_DERIVED); verify against independent run logs.",
    "Using explicit lab-isolated absock base (/Users/mewcapoo/Projects/proton-macos-lab/.s); host /tmp relay bypassed.",
    "No native macOS Steamworks bridge is provided by this launcher."
  ],
  "runtime_descriptor": {
    "path": "/Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-socket-derived/build/elfuse",
    "sha256": "06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d",
    "flavor": "derived",
    "source_baseline": "ABSOCK_CUSTOM_BASE_DERIVED",
    "commit": "8612033dab8dc60728f604a4ea0441895fc16d39",
    "patches": [
      "layout_shift",
      "futex_wait_wake",
      "preempt_lifecycle_stop_join",
      "absock_custom_base"
    ],
    "description": "Derived elfuse with lifecycle stop/join and explicit lab-only absock base relay",
    "capabilities": {
      "supports_absock_base": true
    },
    "execution_evidence": "NOT_CHECKED"
  },
  "absock_base": "/Users/mewcapoo/Projects/proton-macos-lab/.s",
  "execution_performed": false
}
```

---

## 5. 验收交接与冻结说明

1. **未执行真实 Wine**：
   严格遵守并发红线，生成候选时保持 `execute_runtime: false`，wrapper 仅输出 `PLAN_READY` 计划，未拉起任何底层 Wine / FEX 进程，绝不干扰 task-42 的并行运行。
2. **既有候选冻结不动**：
   既有的 `artifacts/steam-prepared/runtime-handoff-*` 候选目录及配置文件未发生任何编辑或覆写。
3. **交付完成**：
   所有修改收敛在 task-44 指定 writeScopes 内，自检全绿。
