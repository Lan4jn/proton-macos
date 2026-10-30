# P0 Wine baseline 接入判定

状态：NOT_RUN_ADAPTER_PENDING（真实原 runtime/C 派生对照未执行）。fixture 治理门已经独立 reviewer PASS，不等于 Wine 清理已验证。

## 只读事实
- 原 runtime：sources/elfuse-once-panorama2-derived/build/elfuse，SHA256 8180332221745ee0a1870d1bf588ce97cb72fa1dc9a7e8f0c89af918ff0abcda。
- C 派生：sources/elfuse-inproc-present-derived/build/elfuse，SHA256 3b146bbe872aaff1554fe887f419539b8f32747062b66c1afb7f96c661cab926。
- 拟共用 PE：fixtures/runtime/pe-worker/pfx/drive_c/minimal-x64.exe，SHA256 87406032e5b7c6546afe5fa0f03847a5e398cb4981c969604417a828ab266bc8。
- prefix 模板37M、1583链接，1577原本broken。6条有效：c:在prefix内；z:指LAB；4个DLL(kernel32/kernelbase/libarm64ecfex/ntdll)指bundle内aarch64-windows。Lead批准副本c保留、z指run/work、4 DLL仅物化副本，broken如实保留。**本轮未复制或启动该prefix。**
- Wine源码server/main.c:60/81有-f foreground；server/request.c:885-926默认fork+setsid，foreground分支不fork。
- 原runtime源码src/syscall/proc-identity.c:371-387的guest setsid只改guest registry；src/runtime/forkipc.c:1661-1663、1710的host posix_spawn仅CLOEXEC_DEFAULT，不设PGROUP。仅源码推断，未绑定准确二进制构建或实测host PGID，因此未将其当清理保证。

## 接入门与拟定预算
下一独立任务先静态/fixture证明确切runtime guest fork+setsid的host PGID归属，或实现明确-owned foreground wineserver接入并独立审查。之后才同PE、同Wine、新prefix、无ELFUSE opt-in一轮对照；elfuse内部20s、supervisor25s、outer30s分层记录。冷启动预算不足不等于死锁，不因无新证据盲增预算。本轮不新增该适配器，不运行旧入口。

## 当前支持边界
owned PGID内清理已由fixture验证；自行setsid逃逸、外层父监督器SIGKILL、恶意同用户干预不在保证范围。target_exit=null并target_exit_observed=false表示未观测退出，不是成功。cleanup complete表示无非zombie存活成员；不是全系统无相关进程声明。
