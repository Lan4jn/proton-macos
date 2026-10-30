# 已验证实验的复现入口

> 最新验收补记：Lead `logs/lead-round7/backend-post-wait-fix.log` 新跑后端63项通过且无ResourceWarning；`quickstart-absock-plan.json` 确认为PLAN_READY/execution_performed=false。上游HEAD仍8612033d...且clean，f2/06/phase库摘要未变，派生Proton脚本与公开包解压原件cmp退出0。Windows图形目标仍未通过，具体失败和对照见FINAL.md。


工作目录：`/Users/mewcapoo/Projects/proton-macos-lab`。这是实验后端，不是已安装到原生 Steam 的可玩游戏发行包。

## 1. 运行时与来源边界

- 上游 elfuse 固定提交：`8612033dab8dc60728f604a4ea0441895fc16d39`，原目录保持 clean。
- 本轮生命周期派生构建：`sources/elfuse-lifecycle-derived/build/elfuse`，SHA-256 `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`。
- Proton 来自公开再分发 seed，已核发布者摘要和关键文件；不是独立 Valve 签名认证。原脚本与包内原件 `cmp` 一致。
- Linux 用户态：`fixtures/runtime/arch-case`，大小写敏感 APFS 镜像挂载；无 Linux 内核 VM。
- 真正 Linux Python：`fixtures/runtime/arch-case/usr/bin/python3.14`，SHA-256 `c6bc1ef497b896b7575c546b13f9bafe52e2066f184fdd3fec6af4b5b6349947`。

## 2. 查看启动计划：默认不执行 Wine/Proton

```sh
python3 -m scripts.backend.cli \
  --engine proton \
  --elfuse sources/elfuse-lifecycle-derived/build/elfuse \
  --sysroot fixtures/runtime/arch-case \
  --linux-python fixtures/runtime/arch-case/usr/bin/python3 \
  --runtime-bundle fixtures/runtime/proton-derived \
  --prefix fixtures/runtime/steam-review/compat/pfx \
  -- runinprefix 'C:\hello-x64.exe'
```

预期是 `PLAN_READY`，并非运行成功。运行时描述符可能标记 `CUSTOM_UNVERIFIED_DERIVED` / `NOT_CHECKED`：静态描述符没有导入历史运行证据，这是刻意保留的分层。

## 3. 显式运行已经准备的离线 Steam-shaped 候选

仅调用显式激活的候选。命令会在 lab prefix 内启动真正 Proton，并写唯一运行日志；不要同时运行多个重 Wine 实验。

```sh
'/Users/mewcapoo/Projects/proton-macos-lab/artifacts/steam-prepared/runtime-handoff-review-f2-exec/proton-wrapper.sh' \
  -- runinprefix 'C:\hello-x64.exe'
```

独立验收日志：`logs/steam-handoff-review/run-9wflgjgy`，目标输出 `X64_FEX_OK`、整体和目标退出码均 0、40.47s、无超时。包装器输出 JSON 指向实际目标 stdout/stderr；包装器本身不保证把目标 stdout 原样转发到终端。初始较长超时仍保留，不能承诺每次固定耗时。

`artifacts/steam-prepared/runtime-handoff-review-plan/` 是默认计划态候选；执行能力与安装状态分开，所有 `install-plan.json` 的 `applied=false`。本实验没有将候选复制到真实 Steam。

## 4. 图形底层的实际已测范围

```sh
python3 scripts/runtime/software_vulkan/run_software_vulkan_probe.py
python3 scripts/runtime/vulkan_queue/test_pattern_classifier.py
python3 scripts/runtime/vulkan_queue/run_queue_fill_probe.py
```

隔离 lavapipe/LLVM 来自 Arch ARM HTTP 镜像，文件本地 SHA 已记录，但 PGP 与 repo-db 预期摘要尚未校验。它枚举 CPU `llvmpipe`，不是 Apple GPU/Metal。后一个实测创建 Vulkan 逻辑设备、提交 `vkCmdFillBuffer`、等待 Fence 后回读 256B，正常 coherent 路径 64 字全匹配 `0x1234ABCD`。未验证 compute shader、图形 draw、swapchain 呈现；non-coherent 回退与超时清理故障路径未验收。

## 4a. 显式 lab 套接字中继：只查看新后端计划

新派生 `sources/elfuse-socket-derived/build/elfuse`（SHA-256 `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`）支持显式原生环境变量 `ELFUSE_ABSOCK_BASE`。已有目录 `.s` 必须保持当前用户所有、0700、真实非软链接；计划不会创建或修复目录。旧 f2 或未知 hash 搭配该选项会返回 BLOCKED/20，不会静默忽略。

```sh
python3 -m scripts.backend.cli \
  --engine proton \
  --elfuse sources/elfuse-socket-derived/build/elfuse \
  --sysroot fixtures/runtime/arch-case \
  --linux-python fixtures/runtime/arch-case/usr/bin/python3.14 \
  --runtime-bundle fixtures/runtime/proton-derived \
  --prefix fixtures/runtime/steam-review/compat/pfx \
  --absock-base /Users/mewcapoo/Projects/proton-macos-lab/.s \
  -- runinprefix 'C:\hello-x64.exe'
```

独立计划态候选：`artifacts/steam-prepared/socket-review-plan/`，`applied=false`、`execute_runtime=false`。描述符的 `supports_absock_base=true` 来自已知二进制摘要，`execution_evidence=NOT_CHECKED` 不会被静态能力字段覆盖。当前执行前会重检路径、权限和叶子软链接，但同属主同0700的同名目录换 inode 尚未绑定原始目录身份，见 `reports/socket-backend-review.md`。

## 5. 回归与保留失败

```sh
python3 -m unittest discover -s tests/backend -v
python3 -m unittest scripts.runtime.fex_init.test_diagnostics scripts.runtime.fex_init.test_classifier -v
python3 -m unittest discover -s tests/steam -v
sources/elfuse-lifecycle-derived/build/test-preempt-lifecycle-host
```

原件/来源和此前快速分层总审计见 `reports/continuation-final-review.md`：当时 123 项中 122 PASS、1 项 live Steam 测试显式 SKIP。新增中继参数后，后端单独的最新执行员与独立审查均为 63 PASS，独立负例另有 12 PASS；其它 probe/fake 测试分别记账，不简单合并成游戏通过率。单元测试不替代真实目标执行。

已保留的失败包括原始 elfuse 跨进程 futex / spawn errno、layout-only hello 输出后崩溃、一次新 Proton 组合链 110s 超时、完整 `run` hello 桌面建窗 150s 超时、默认 freedreno Vulkan 设备枚举 -3。后续派生成功不覆盖这些历史事实。

## 6. 安装与后续边界

真实 Steam 客户端检测、兼容工具下拉选择、点击 Play、Steamworks/DRM、实际游戏和窗口呈现尚未验证。Windows x64 `winevulkan` 桥见 `reports/windows-vulkan.md`、`reports/xvfb-wine.md` 与 `reports/wine-badalloc-review.md`：目标 PE 实例创建尚未返回，Wine 内部实例创建不等于目标成功；后续异常观测仍在推进。没有真实安装，因而本轮没有执行卸载/回滚；未来安装前仍需另行保留目标备份并验证目标身份。实验原包、失败记录和已冻结二进制均保留。
