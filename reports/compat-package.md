# Task-138：离线可安装兼容工具包

## 结论与边界
交付为**离线可安装包**，不是完整宿主环境，不宣称已完成真实 Steam 接入。真实 Steam 发现、启动均 UNKNOWN。本轮未写真实 Steam，未执行 guest 游戏或图形探针；ARM64 包也不代表 x64 图形路线已通过。

包目录：logs/compat-package/proton-macos-lab-arm64-diag/

- 约 3.0GiB；清单常规文件总字节 3,167,344,991，不含清单自身。
- 8,107 项：8,105 常规文件、2 个包内相对目录链接。安装清单加 SHA256SUMS.json 共 8,108 项。
- 包内 payload 完整，外部 Python、elfuse、sysroot、适配器工作区等仍须存在，详见后文。

## 包结构及模块配对
    proton-macos-lab-arm64-diag/
      compatibilitytool.vdf
      toolmanifest.vdf
      version
      proton-wrapper.sh
      config.json
      proton / filelock.py
      LICENSE / LICENSE.OFL / PATENTS.AV1
      proton_3.7_tracked_files / steampipe_fixups.py / steampipe_fixups.json
      user_settings.sample.py
      external-dependencies.json
      SHA256SUMS.json
      files/
        bin -> bin-arm64
        bin-arm64/
        lib/wine/aarch64-unix/
        lib/wine/aarch64-windows/
        lib/wine/{i386-windows,x86_64-windows,dxvk,vkd3d-proton,...}/
        share/default_pfx_arm64/
        share/...

完整路径树：logs/compat-package/package-tree.json。逐文件 SHA、尺寸及模式：包内 SHA256SUMS.json；不自引用，其自身 SHA 单列收据。

- win32u.so：59a76b05d943bdb3e92538eb641b979e6d432897afcfd4e801c3b177040478ed。
- shipped winevulkan.so：2786ca6f5f440821972e91a371e609d2d482597a8b6d75bcf02e287f83eea9ab。
- shipped ntdll.so：d2d734b53183750f27bd0c7a4093b6665fc94947a38d1bc444411fe6c85fc296，与原 fixture 逐字节一致，未引入 task136 候选。
- 其余文件复制自原 proton-derived/files，未修改 fixtures。
- 两个目录链接为 files/bin→bin-arm64 和 files/share/wine/mono/wine-mono→wine-mono-11.3.0，都在包内。
- 原 1,821 个文件链接在包副本中物化为相同字节的常规文件，以匹配现有安装器对文件软链接的解引用行为。包内没有指向原 fixtures 的外链。

## 独立 VDF 解析与扫描模型
新脚本独立实现 KeyValues 子集解析，不调用原 steam_plan.parse_valve_vdf。支持引号、转义、花括号、行注释；重复键、截断和非法 token 报错。仅覆盖本包格式，不代表完整 Valve 解析器。

| 字段 | 实际值 |
|---|---|
| compatibilitytools/compat_tools/name | proton-macos-lab-arm64-diag |
| install_path | . |
| display_name | Proton macOS Lab ARM64 (Diagnostic CPU Vulkan) |
| from_oslist | windows |
| to_oslist | macos |
| manifest/version | 2 |
| commandline | "/proton-wrapper.sh" -- %verb% |

前导斜杠按现有生成器约定解释为工具根下路径。离线测试将其解析成安装目录内入口，不声称普通 shell 会这样解释 /proton-wrapper.sh，也不声称 Steam 客户端已证实该解释。

扫描模型只读 compatibilitytools.d 的直接子目录；列出本工具、忽略 not-a-tool 和 malformed。模型限定本包 install_path=.、macos 字段，忽略目录软链接；这不是完整 Steam 扫描实现，不外推其实际行为。

证据：build-result.json、installed-vdf.json、scan-result.json、manual-scan.json。

## SHA 与安装 manifest 一致性
常规文件检查 SHA/尺寸/模式，目录链接检查 target 和链接文本 SHA；安装后重算全清单。现有 manifest 的逐项 SHA、常规文件类型及链接标记与独立清单比较，路径集合等于包清单路径加 SHA256SUMS.json。

清单自身 SHA：12190148816a97965eca4996e2e679603bc5dbb4e71b27bb019ae9da2a16690d。

## 离线 apply / verify / rollback 实测
新脚本：scripts/backend/build_compat_package.py。复用已验收 backend 的 plan/apply/verify/rollback，不修改原脚本。写命令限制在 logs/compat-package 下，不接受真实 Steam 根。

1. 模拟 sandbox-steam 保留 unrelated marker 与两个非工具目录，保存前置指纹。
2. 完整安装及原 verify 通过，再比较包清单与安装 manifest。
3. 扫描只列出本工具。
4. 源包临时移到 -MOVED，目标 wrapper 以 invalid-offline-verb 实跑，exit 2 到达适配器并在运行时启动前报未知 verb；这不是游戏启动。
5. 源包仍移开时，安装目录临时 plan-only 配置明确 execute_runtime=False，真实适配器读安装 config、runtime_bundle=$DIR 与外部依赖得到 PLAN_READY，exit 0；移除临时文件后全清单再验通过。原 config 保持 execute_runtime=True。
6. 恢复源包后回滚，目标工具消失，前后指纹一致，无关条目保留。

最终收据：OFFLINE_PACKAGE_VERIFIED；source_moved_wrapper_check=true、installed_positive_plan_ready=true、rollback_status=success、rollback_fingerprint_equal=true；runtime_execution_this_task=false。

### 已逐字实跑的命令
工作目录 /Users/mewcapoo/Projects/proton-macos-lab：

    python3 scripts/backend/build_compat_package.py test
    python3 scripts/backend/build_compat_package.py verify
    python3 scripts/backend/build_compat_package.py install --root logs/compat-package/manual-offline-steam --manifest logs/compat-package/manual-installation.json
    python3 scripts/backend/build_compat_package.py scan --root logs/compat-package/manual-offline-steam/compatibilitytools.d
    python3 scripts/backend/build_compat_package.py rollback --root logs/compat-package/manual-offline-steam --manifest logs/compat-package/manual-installation.json

安装实际输出：INSTALLED_OFFLINE、verified=true、manifest_entries=8108、package_manifest_matches_install_manifest=true。回滚：success、files_removed=8108、errors=[]。

为保留证据，安装不覆盖已有 manifest，build 不覆盖已有包。manual-installation.json 已实跑留存，重跑时请使用新的 logs/compat-package 子目录和 manifest 名，不覆盖本轮。

## 包外依赖（必须由环境提供）
包内 external-dependencies.json 保存准确路径与关键哈希；config.json 是实际配置。

| 依赖 | 当前路径/约束 |
|---|---|
| 宿主 Python | /Library/Developer/CommandLineTools/usr/bin/python3；wrapper 冻结绝对路径 |
| 宿主 shell | /bin/sh |
| 工作区适配器 | lab/scripts/backend/steam_handoff.py、bundle.py、process.py、supervisor.py，未打入包 |
| elfuse | lab/sources/elfuse-once-panorama2-derived/build/elfuse，SHA8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda |
| Linux sysroot | lab/fixtures/runtime/arch-case，须保持挂载与内容可用 |
| 客态 Python | config 实际解析到 sysroot/usr/bin/python3.14，来源 python3 链接 |
| CPU ICD/库 | lab/fixtures/runtime/lavapipe-derived 中 lvp_icd.json 与 usr/lib（含 LLVM23.1 等） |
| bundle 元数据 | lab/artifacts/public-proton/bundle.json |
| 独立可写 prefix | lab/logs/compat-package/compat-data/pfx，已复制完整测试 prefix；不属包 payload |
| 可写日志 | lab/logs/compat-package/runtime-logs |
| 宿主能力 | Apple Silicon macOS 的 Hypervisor 执行条件，非包文件 |

lab 表示本报告工作目录。现有 adapter 强制 lab-local 路径，所以 payload 可在当前工作区模拟根内迁移，不是任意机器开箱即用发行包。真实 Steam appid→prefix 选择未集成，当前 prefix 固定。

config 保留 ELFUSE_DIAG_SESSION_SHARED=1、LP_NUM_THREADS=1、客态 LD_LIBRARY_PATH、110s 超时。诊断共享门牺牲正常 private COW 语义。成果仍限 CPU llvmpipe，不宣称硬件 GPU 支持。

## Valve 格式证据与未证项
曾尝试读取 ValveSoftware/Proton 官方模板：gh 缺失，raw 请求超时或404，未获得有效新副本；零字节文件不作为官方证据。因此不宣称最新 Valve 规范已全面核验。

- 已证：与现有已验收生成器字段一致；独立语法/字段、扫描模型和本地可逆安装通过。
- UNKNOWN：macOS Steam 是否扫描该工具、是否接受 to_oslist=macos、是否按预期解释前导斜杠、是否正确替换 %verb% 和选择应用。
- UNKNOWN：真实 Steam 客户端识别与启动。未触碰真实 Steam、未登录或运行 GUI。
- 已知功能缺项：宿主运行时及 adapter 外置、固定 fixture prefix。本包不是官方 Proton 的 macOS 支持实现。
- 没有获取可靠官方文档新证据，未作违反某条已核实 Valve 条款的断言；上述规则未核项逐条保持 UNKNOWN，扫描模型不冒充客户端。

## 测试与问题收敛
- 新脚本7项测试 PASS：VDF转义、重复/截断、字段/commandline错误、扫描误列、损坏清单、外链、文件链接物化（tests-final.log）。
- 原 backend 90 tests，7.181s，OK（backend-tests.log），原实现未修改。
- 初次构建遇副本 win32u 只读模式，build.log保留；仅chmod新包副本后替换。失败包保存在build-failed-readonly。
- 初次e2e文件链接类型与安装表达不一致，失败安装已用原rollback清理，failed-* manifest及日志保留；物化新包文件链接后最终e2e及manual实跑通过。
- 失败记录保留，不用来冒充最终成功。

## 证据索引
以下均在logs/compat-package：

- receipt.json / build-result.json / verify-final.json / package-tree.json
- installation-manifest.json / installation-manifest.plan.json
- fingerprint-before.json / fingerprint-after.json / rollback-result.json
- installed-wrapper-check.json / installed-plan-check.json / installed-vdf.json
- scan-result.json / manual-install.log / manual-scan.json / manual-rollback.log
- tests-red.log / tests-green.log / tests-final.log / backend-tests.log
- e2e-final.log / 包内external-dependencies.json / 包内SHA256SUMS.json

最终范围：离线可安装包与发现模型验证，不等于真实 Steam 接入、客户端启动或 x64 图形成功。
