# task139：真实 Windows x64 窗口对象、消息循环与 GDI

## 分层结论
- Win32窗口对象创建：PASS。
- ShowWindow、真实 GetMessage/DispatchMessage、WM_PAINT(15)、GDI绘制、PostQuitMessage、DestroyWindow、正常exit0：PASS。
- 宿主可见窗口/屏幕呈现：UNKNOWN；现有trace明确 null driver，不能据GDI返回声称macOS屏上能看到窗口。
- 输入事件可达：UNKNOWN；游戏兼容与硬件GPU：UNKNOWN。
- 完整Proton run verb：本轮额外对照FAIL，首错是prefix缺tracked_files，尚未到PE入口；不等同建窗timeout。

## 构建
sources/win-window-probe/window_x64.c 零CRT，动态LoadLibrary user32/gdi32以记录DLL加载前后。
sh sources/win-window-probe/build.sh

file：PE32+ executable (console) x86-64, for MS Windows。
SHA256：d6625afe061295e9c02525a15214054c5615eca8db6b5ac348f5c570e7c02365。
Clang -target x86_64-windows -O2 -ffreestanding -fno-builtin；llvm-lib /machine:x64；lld-link /entry:mainCRTStartup /subsystem:console /nodefaultlib。

## 基线真实时间线
安装目标wrapper，源目录移开，独立完整pfx，runinprefix C:\window_x64.exe。
总wrapper时间78.256571292s；adapter exit0、target_exit0、timed_out=false、cleanup_errors=[]。
PE入口到退出21.045s，GetTickCount64相对PE起点：

| 阶段 | 开始ms | 返回ms | 用时ms |
|---|---:|---:|---:|
| USER32加载 | 0 | 357 | 357 |
| GDI32加载 | 357 | 357 | 0 |
| RegisterClassEx | 357 | 21035 | 20678 |
| CreateWindowEx | 21035 | 21038 | 3 |
| ShowWindow | 21038 | 21040 | 2 |
| GetMessage循环 | 21041 | 21044 | 3 |
| WM_PAINT BeginPaint/FillRect/TextOut/EndPaint | 21041 | 21043 | 2 |
| DestroyWindow | 21044 | 21045 | 1 |
| EXIT_OK | - | 21045 | - |

收到消息528、528、15、528；15为真实WM_PAINT，经DispatchMessage到窗口过程。ShowWindow返回0是原先不可见状态，不是失败。WM_PAINT调用后PostQuitMessage，GetMessage返回0，再显式销毁窗口正常退出。
初步慢点是RegisterClassEx内20.678s，不是CreateWindowEx；总wrapper与PE时钟区间不可直接归因于同一函数，剩余57.212s含启动/Proton/Wine/清理等，尚未细分。此轮不曾挂死，无需以猜测栈代替真实完成标记。

## 显示驱动边界
baseline/probe.stderr.log 45211字节，SHA0878f85d69e6b091606cc58ef58796dda9df6f2702901c62ad8314079254ea54。
- 行52/76：explorer:load_graphics_driver ... using null driver。
- 行53/77：driver L"null"。
这是明确选择记录，不是仅因没有x11drv字样作推断。task140继续查源码选择和20.7s来源。

## 完整run额外对照
fullrun 0.823220792s，exit1、无timeout，PE阶段标记为空。
首错：Proton update_builtin_libs读取本轮compat/tracked_files不存在，FileNotFoundError；完整run会执行prefix setup，runinprefix跳过该升级路径。因此不能把此轮失败归因建窗，也不能把runinprefix成功包装成完整run已修复。
不叠加修改原launcher；保留raw并交Lead。

## 超时与清理预算
runner请求adapter timeout=115s，外层125s；底层argv仍带既有elfuse --timeout 90（读取实际adapter_result确认），本轮成功在78.257s内，未触及任何超时。若后续要验证110-120s内核运行，必须把这个底层90s配置也纳入调整，不能只修改adapter外层并声称全链预算115s。
外层runner owned process group，运行时仍由既有run_isolated/supervisor管理与清理；无killall。目标安装结束后原rollback返回success、前后树指纹一致。

## 证据
- logs/win-window/build.log：构建类型及SHA。
- tests-red.log/tests-green.log：3项时间线单元测试，完整链通过、仅建窗timeout失败、非0退出失败。
- baseline/{receipt.json,timeline.json,probe.stdout.log,probe.stderr.log,wrapper.stdout.log,wrapper.stderr.log}。
- baseline/runtime-logs/run-xsb71mt3 原始运行目录。
- fullrun/{receipt.json,timeline.json,probe.stdout.log,probe.stderr.log}；run-0fpfepik保留首错。
- 各轮installation-plan/manifest、fingerprint-before/after、rollback.json。

## 配置保持
win32u 59a76b05，shipped winevulkan，ELFUSE_DIAG_SESSION_SHARED=1，独立prefix及包内default_pfx；已有backend、runtime和原fixtures保持只读，无commit/push、无真实Steam修改。既有图形基线为llvmpipe CPU，不代表硬件GPU。GDI成功不是Vulkan swapchain或宿主呈现成功。
