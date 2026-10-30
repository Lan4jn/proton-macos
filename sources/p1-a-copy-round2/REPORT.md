# P1 A-copy 第二轮：全场景终态综合验证报告

## 1. 结论与状态边界

- 综合状态：**PARTIALLY_VERIFIED (Host Subsystem Verified, P1 Transport Overall NOT_READY)**
- 范围：严格限定在 `sources/p1-a-copy-round2`、`scripts/p1_a_copy_round2`、`tests/p1_a_copy_round2`、`logs/p1-a-copy-round2`。未改动原 runtime/Wine/历史第一轮证据，未改动真实 Steam/系统/全局包，无 git commit/push。
- 事实界定：**CPU 生成的 RGBA8 payload 仅作为 host 独立呈现进程与 IPC 协议的传输/架构证据，不声称真实 GDI/Wine 已通过，未进行真实 Linux guest 运行，绝不进入 P2**。

## 2. 监督架构与协议断言补齐

本轮完成了 P0 单进程组监督适配与协议集中加固：
1. **单一 Owned Session 治理**：只读复用已冻结 P0 runner/worker/cleanup（SHA256: `3580ea64ca56bce11439ae8b3e93f859feceec70555d2fb98bc3e7f8ef63a13b`），producer 与 host 均通过普通 `Popen` 继承 worker 同一进程组（PGID），禁止子进程 `start_new_session`；
2. **独立 Outer Watchdog**：外层总 deadline 独立于内层超时；超时直接由 P0 父监督器核验 leader 身份后向整组发送 `SIGTERM` → 限时 `SIGKILL`；
3. **有界 I/O 与非阻塞 Deadline**：连接采用非阻塞 `connect_ex` + `select` + `SO_ERROR`；发送/接收均强制绝对单调 deadline，彻底避免半包无 EOF、大 payload 背压或永不 ACK 导致的无限阻塞；
4. **协议断言加固**：
   - 显式断言 `sid == 1`；
   - 检查所有 ACK payload 必须为空；
   - 显式校验 `slot in (0, 1)`，且每帧 seq 的 RECEIVED 与 CONSUMED slot 严格配对一致；
   - 校验 terminal `disposition in ('displayed', 'replaced', 'invalidated')`；
5. **变异负测通过**：16 项单测 + 7 项 reviewer 变异负测 + 3 类 extra 变异负测（漏 terminal、错 gen 未拒、窗口外 HANDLED）全部验证通过，成功拦截并致退出非 0。

## 3. 固定 Binary 真实 Host 全场景长测结果

使用固定 AppKit presenter 二进制（SHA256: `b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`），在 Lead 授权下完成全部实测场景：

### 3.1 核心长测场景 (使用 `scripts/p1_a_copy_round2/probe.py`)
1. **1000 帧变化帧正确性长测 (`r2-correctness-01`)**
   - 运行：`runner.py --run-id r2-correctness-01 --timeout 75 --outer-timeout 85`
   - 结果：Runner exit `0`, Host exit `0`, 耗时 `9.18s`；
   - 验证：1000 帧全部完成 RECEIVED 与 CONSUMED，NSView cache 逐像素核验一致（`capture_match: 1`），`displayed: 1000`, `replaced: 0`, `invalidated: 0`；
   - 证据：`logs/p1-a-copy-round2/r2-correctness-01/receipt.json` (`914cb723526ed18b30ac5305378d8c82c97823c83c7868d1c1fca9cfdc163383`)。
2. **30 秒 720p30 吞吐长测 (`r2-throughput-01`)**
   - 运行：`runner.py --run-id r2-throughput-01 --timeout 50 --outer-timeout 60`
   - 结果：Runner exit `0`, Host exit `0`, 整体耗时 `30.85s`（输入持续 `30.004s`）；
   - 验证：输入 900 帧，全部 RECEIVED 与 CONSUMED，`displayed: 900`, `replaced: 0`, `invalidated: 0`；有效载荷 3.318 GB (约 `110.575 MB/s`)；
   - 分位：RTT p50 `13.03ms` / p99 `18.73ms`；Host age p50 `5.14ms` / p99 `9.75ms`；
   - 证据：`logs/p1-a-copy-round2/r2-throughput-01/receipt.json` (`ad28b52b5a399dac3d15c93e5296d501f07d4a1ced724c95c40745f65cfc7f1c`)。

### 3.2 增量场景 (使用 `scripts/p1_a_copy_round2/scenario_extra_v2.py`)
3. **Latest-frame-wins 场景 (`r2-latest-01`)**
   - 运行：`runner.py --run-id r2-latest-01 --timeout 25 --outer-timeout 35` (使用 extra 首版)
   - 结果：Runner exit `0`, 100 帧全部处理，`displayed: 3`, `replaced: 97`；
   - 证据：`logs/p1-a-copy-round2/r2-latest-01/receipt.json` (`f2888d1b71a40f217b9413d5746a636e326df12ee295e6893f940b0c106563c6`)。
4. **Resize 与旧代拒签 (`r2-resize-02`)**
   - 运行：`runner.py --run-id r2-resize-02 --timeout 25 --outer-timeout 35`
   - 结果：Runner exit `0`, seq1(gen1, 64x64) 与 seq2(gen2, 32x48) 正常显示，seq3(旧gen1) 被 host 正确以 `ERROR: frame_shape_identity` 拒绝；
   - 注：首版 `r2-resize-01` 因旧代测试发送大 payload 遇 host 提前关闭触发 OS BrokenPipe (exit 1) 证据完整保留于 `logs/p1-a-copy-round2/r2-resize-01/`，不作修改；
   - 证据：`logs/p1-a-copy-round2/r2-resize-02/receipt.json` (`24624529a2319d2e1cd3df7217b319f2775cb28ca855ad051a5b2e00e65f8e32`)。
5. **3 秒纯算期间 UI 预排事件调度 (`r2-busy-01`)**
   - 运行：`runner.py --run-id r2-busy-01 --timeout 25 --outer-timeout 35`
   - 结果：Runner exit `0`, producer 执行无 syscall 纯算 3000.32ms；host 主线程在忙算窗口内调度预排 `ui_event` 并返回 `HANDLED` ACK，producer 在忙算区间内接收到 ACK；
   - 证据：`logs/p1-a-copy-round2/r2-busy-01/receipt.json` (`20449944c893f6ee840779323e91b094692258e1c22c6739d94807acf81428b8`)。
6. **3 秒纯算期间关闭响应 (`r2-busy-close-01`)**
   - 运行：`runner.py --run-id r2-busy-close-01 --timeout 25 --outer-timeout 35`
   - 结果：Runner exit `0`, producer 纯算 3000.32ms；host 主线程在忙算窗口内响应 `close_event` 并返回 `HANDLED` ACK，窗口关闭且触发连接断开；
   - 证据：`logs/p1-a-copy-round2/r2-busy-close-01/receipt.json` (`54cf48ed1ca01b096c7d7fcc197aca7ee05f46ce506d405d5597b5ddd74f4f7d`)。
7. **正常断连清理 (`r2-disconnect-01`)**
   - 运行：`runner.py --run-id r2-disconnect-01 --timeout 25 --outer-timeout 35`
   - 结果：Runner exit `0`, host 在客户端主动 shutdown 探测到 EOF 后有界退出 (exit 0) 并由 P0 完整清理；
   - 证据：`logs/p1-a-copy-round2/r2-disconnect-01/receipt.json` (`df27999ffe5c3ec0956a3b9abda584605d6360a1fc75bbf97edbf2b4ae38d713`)。

## 4. 关键代码与资产清单 (Manifest)

- `scripts/p1_a_copy_round2/runner.py`: `9cba0f274f380bf43a534b4903c76b3e71d1aafa49e0ce8bb5e09951ef759f51`
- `scripts/p1_a_copy_round2/roles.py`: `1a89fe1bb7b71851c443fe7efc2b944d788f4ecc10bf02c53371456bf1079910`
- `scripts/p1_a_copy_round2/deadline_io.py`: `4b2ae4e081669a8cc8196b9db53e70543e482a88986f9f4ccb75ac1f3daf25d7`
- `scripts/p1_a_copy_round2/wire.py`: `239785bd5657a86e1181d9140c0eb9b36f792828f69c212ba9aad827a0fa9dcc`
- `scripts/p1_a_copy_round2/probe.py`: `1319c07f3fe27228a0d9040f4963f611a9abff56aedd17ebbf0c8e242ca36ba0`
- `scripts/p1_a_copy_round2/scenario_extra.py` (首版): `0f5a69f08159d743351288d859aa22d23037bc21bae39c1be87560671346a225`
- `scripts/p1_a_copy_round2/scenario_extra_v2.py` (v2版): `a626e0f615008ddee72645ba56dde00fbe53b729e21ca29037720cfda326781d`
- `tests/p1_a_copy_round2/test_governance.py`: `266d53c9e1991fb3166d2297a82b1cfb1fc16aa541a7256b399bfcd8017728de`
- `tests/p1_a_copy_round2/test_extra_negatives.py`: `a340bed7893f891909e7e9c3647daedf0aea200e6b8e007fe8fdecc7bd1ad55d`
- `sources/p1-a-copy-round2/SPEC.md`: `bfa20a5616a1d68153c0f750e86c9b0ee05537c55160de5087fb4431d4d2696b`
- `sources/p1-a-copy-round2/guest_producer.c`: `fab1f82b94937b938e5d32804a61221472987e690b404663e10c09006cb4992d`
- `tests/p1_a_copy_round2/test_guest_c.py`: `982fce2184adfc86740d4ced8f284fca1073f6bd4347f70bf7e183eb85131bf3`
- `scripts/p1_a_copy_round2/guest_launcher.py`: `937685f7a7cbee3cce75e867e1490006b6fdd76929c2a909de4d9437794a4ae2`
- `tests/p1_a_copy_round2/test_guest_launcher.py`: `5b96f73da83627fca4161400d7fbb1ccb9d67957073c05a7d7028b084d973919`
- `logs/p1-a-copy-round2/build-guest-elf-01/guest_producer_arm64`: `f699318aff3bffb55cf03dddaa69f82c68ace2cee643e64aff8f3a989847e12e`
- `sources/elfuse-once-panorama2-derived/build/elfuse` (固定 original runtime): `8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda`
- `logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter` (固定 host binary): `b605f9faafa231bb4d2b5759bd7eb95a0234c756c209a5d5400455ebf788a5eb`

## 5. 真实 Linux Guest C Producer 单帧实测里程碑 (`r2-g1-01`)

在 Lead 授权唯一 guest 执行锁后，完成真实跨 runtime 单帧连通性验证：
- **运行命令**：
  ```bash
  python3 -B scripts/p1_a_copy_round2/runner.py \
    --run-id r2-g1-01 \
    --timeout 25 --outer-timeout 35 \
    --module host=logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter \
    --module runtime=sources/elfuse-once-panorama2-derived/build/elfuse \
    --module producer_elf=logs/p1-a-copy-round2/build-guest-elf-01/guest_producer_arm64 \
    --module launcher=scripts/p1_a_copy_round2/guest_launcher.py \
    -- /usr/bin/python3 -B /Users/mewcapoo/Projects/proton-macos-lab/scripts/p1_a_copy_round2/guest_launcher.py \
       --scenario smoke \
       --host-binary /Users/mewcapoo/Projects/proton-macos-lab/logs/p1-a-copy-v2/run-4e2a63efe2f2/presenter \
       --runtime /Users/mewcapoo/Projects/proton-macos-lab/sources/elfuse-once-panorama2-derived/build/elfuse \
       --producer-elf /Users/mewcapoo/Projects/proton-macos-lab/logs/p1-a-copy-round2/build-guest-elf-01/guest_producer_arm64 \
       --producer-elf-sha f699318aff3bffb55cf03dddaa69f82c68ace2cee643e64aff8f3a989847e12e
  ```
- **运行结果**：Runner exit `0`, Host exit `0`, Guest exit `0`, 耗时 `1.34s`；
- **跨层通信闭环事实**：
  - Linux aarch64 静态 ELF (`f699`，无 PT_INTERP) 在真实 `elfuse` (`81803322...`) 内成功执行并连接 `/tmp/s`；
  - 真实发送 1 帧 720p RGBA8 (3,686,400 字节) payload，CRC32 `355804070`；
  - Host 独立服务 (`b605`) 正确回复 `stage: RECEIVED` 及 `stage: CONSUMED, disposition: displayed, host_age_ms: 6.637ms`；
  - 双方正常发送并接收 `CLOSE / CLOSED` 握手，干净退出；
  - **界限说明**：本测试中 `capture: false`，严格按照协议不充当屏幕或 view 捕获证据；
- **证据文件与 SHA256**：
  - `logs/p1-a-copy-round2/r2-g1-01/receipt.json` (`dbffe14c8ebf9cb77ecbe362471aac0b5c000ce6c8de99c2f8bd1163ce0bac22`)
  - `logs/p1-a-copy-round2/r2-g1-01/work/result.json` (`a970868ed1215b56839a69101b8fe582c7df4c6e3802774b5c1be4816715ef07`)
  - `logs/p1-a-copy-round2/r2-g1-01/work/host.stdout` (`faf98a74c48a7035102613eeec9b38b11e283b2a30d5eedc6d501e9e22a316e0`)
  - `logs/p1-a-copy-round2/r2-g1-01/work/guest.stderr` (`87e5e4091dac2d941d737a5018bb82f1db79a0a5c126efd320be80ecad3dc890`)
  - `logs/p1-a-copy-round2/r2-g1-01/work/r/bin/producer` (`f699318aff3bffb55cf03dddaa69f82c68ace2cee643e64aff8f3a989847e12e`)

## 6. 最终状态总结与后续边界

1. **A-copy 路线最终状态**：
   - Host 侧全场景（1000 帧逐像素匹配、30s 720p30 吞吐、latest 替换、resize 旧代拒签、3s 忙算预排事件调度、关闭响应、正常断连）：**VERIFIED / PASS**；
   - 真实 Linux Guest 跨层通信（1 帧 720p 真实 payload 传输与握手闭环）：**VERIFIED / PASS**；
   - 真实 Linux Guest 1000 帧与 30s 长测：依据 Lead 决议止于单帧 smoke，**明确为 NOT_RUN**；
   - 真实 Wine / GDI 驱动：**明确未实现，绝不进入 P2**。
2. **锁与后台治理**：
   - Guest 锁已彻底释放，不再运行任何 guest 进程；
   - 无任何遗留未回收后台任务。
