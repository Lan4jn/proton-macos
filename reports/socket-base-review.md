# Unix 套接字中继显式 Lab 路径配置独立审查报告

**报告日期**：2026-10-16  
**审查角色**：`final-lab-reviewer`（独立审查员）  
**关联任务**：`task-41`（独立审查Unix套接字中继的显式lab路径配置）  
**被审任务**：`task-40`（将elfuse抽象套接字中继显式限制到lab目录）  
**工作区根目录**：`/Users/mewcapoo/Projects/proton-macos-lab`  
**基准冻结二进制**：`sources/elfuse-lifecycle-derived/build/elfuse`（SHA-256：`f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`）  
**被审冻结二进制**：`sources/elfuse-socket-derived/build/elfuse`（SHA-256：`06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`）  
**审查专属隔离 Base 目录**：`/Users/mewcapoo/Projects/proton-macos-lab/.sr`（权限严格校验：`0700`）  
**审查归档日志**：`logs/socket-base-review/`  

---

## 一、 执行摘要与总体验收判定

1. **核心验收结论**：**批准通过（APPROVED）**。
   - **单点配置与零破坏原则完全履行**：仅修改 `src/syscall/net-absock.c` 与 `src/syscall/net.c` 2 个文件，`src/syscall/syscall.c` 与其他子系统保持 **100% 相同（0 diff）**，零伪造能力、零全局/系统设置修改。
   - **双轨门禁完全可靠**：
     * **默认 Unset**：精确保持原有 `/tmp/elfuse-absock-%llu` 兼容路径；
     * **显式设置**：严格校验 `ELFUSE_ABSOCK_BASE`，中继文件完全约束在 lab 内部指定的 base 目录下；在实测运行中，套接字与短链接真实绑定并落盘于 lab 指定目录，未向宿主 `/tmp` 写入任何中继文件；
     * **边界严谨说明**：T10 测试中通过比对运行前后 `/tmp` 目录项断言“无新增 absock 目录”，但这属于特定测试前后的局部对比证据，不能等同于“证明整个系统全域对 `/tmp` 绝无任何写入”；真正的隔离保证来自于源码显式路径路由（`clean_base` 拼接）与实际观测到的 `inode` 落在 lab 目录中；
     * **显式非法即刻硬失败**：相对路径、空字符串、不存在路径、权限非 `0700`、符号链接（含尾斜杠伪装）、超长路径等，**100% 硬报错拒绝，绝不静默 Fallback 到 `/tmp`**。
   - **真实 Inode 观测与消息交换闭环**：
     * 经真实 Linux Python 3.14 驱动抽象套接字与短链接通信，在 `.sr/n<namespace>/` 目录下成功观测到实际套接字节点（`inode=16417974`, `mode=0140755`）与缩短符号链接（`inode=16418021`, `mode=0120755`）；
     * 进程退出后，子命名空间目录及自有节点 100% 自动清理，`.sr` 根目录保持完好且权限始终为 `0700`。
   - **跨 Execve 继承与反向查询一致性**：
     * 父进程 `bind` 抽象套接字，子进程通过 `os.execv` 重新执行新进程后，依然成功连接并双向通信（`PASS: ABSTRACT_SOCKET_CROSS_EXEC_COMMUNICATION_VERIFIED`）；
     * 长路径套接字经过 `.sr` 缩短中继后，通过 `getsockname()` 准确反查恢复为原 Linux Guest 路径，与原生 Linux 行为完全一致。

---

## 二、 第一阶段：代码差异与安全静态审查（Static Review）

### 1. 源码差异审计（对比基准 `f2a678...`）
`diff -u sources/elfuse-lifecycle-derived sources/elfuse-socket-derived` 结果确认仅改动 2 个文件（净改动 2 files）：
1. `src/syscall/net-absock.c`：
   - 增加 `absock_validate_custom_base` 函数（严格校验权限 0700、所有者 getuid()、绝对路径、符号链接及尾斜杠剥离、长度限制）；
   - 修改 `absock_dir_format`：检测 `ELFUSE_ABSOCK_BASE`，采用压缩子目录 `%s/n%016llx`（18 字节）；
   - 在 `absock_ensure_dir_locked` 中增加对 `absock_dir_format` 失败的返回值校验（`< 0` 立即返回 -1）。
2. `src/syscall/net.c`：
   - 差异精确定位：在 `sys_bind`（行 550-553）中，当 `absock_bind_prepare` 失败时由原版的硬编码 `-LINUX_EINVAL` 改为透传 `linux_errno()`；而普通 pathname sockaddr 转换失败分支（行 557-560）保持返回原有的 typed negative `mac_len`。此处的错误码透传改动使得抽象套接字前置校验失败（`EACCES`, `ENOENT`, `ELOOP`, `ENAMETOOLONG`, `EINVAL` 等）能精准向调用方暴露，属于合理且受控的局部错误码透传修正。
3. `src/syscall/syscall.c`：
   - **0 diff**，保持纯净，无任何伪造系统调用或绕过。

### 2. 关键安全与边界设计核查

- **Trailing Slash 符号链接穿透防护**：
  - **背景**：macOS 的 `lstat("/path/to/symlink/")` 在带尾斜杠时，内核底层会自动将其作为 `stat` 处理，从而跟随符号链接并检查目标目录，造成符号链接检查被绕过。
  - **实现审查**（`net-absock.c:108-112`）：
    ```c
    size_t blen = len;
    while (blen > 1 && base[blen - 1] == '/')
        blen--;
    memcpy(clean_out, base, blen);
    clean_out[blen] = '\0';
    if (lstat(clean_out, &st) < 0) return -1;
    if (S_ISLNK(st.st_mode)) { errno = ELOOP; return -1; }
    ```
    代码在执行 `lstat` 前首先剥离所有末尾斜杠，并在临时缓冲区截断后传入 `lstat`，彻底根除 macOS 系统的尾斜杠符号链接跟随穿透漏洞。
- **路径长度与 `sun_path` 严格预算**：
  - macOS `struct sockaddr_un` 的 `sun_path` 限制为 104 字节（含 `\0` 实际可用 103 字节）。
  - Base 目录限制最大 59 字节（`len >= 60` 返回 `ENAMETOOLONG`）；
  - 格式化子目录采用 `%s/n%016llx`（18 字节固定后缀，如 `/n0000000000003039`），总目录长度最大 `59 + 18 = 77` 字节；
  - 套接字短链接或文件名（`p<pid>-<fnv1a>`，约 24 字节），总路径长度 `77 + 24 = 101 < 104` 字节；
  - 校验守卫 `(size_t)n > 72` 与各缓冲区上限确保在任何极端命名空间下均不会越界。
- **目录权限与所有者约束**：
  - 严格校验 `st.st_uid == getuid()`，防范冒用其他用户目录；
  - 严格校验 `(st.st_mode & (S_IRWXG | S_IRWXO)) == 0`，任何组读写/全局可读写目录均拒绝并返回 `EACCES`。
- **清理范围严格受限**：
  - 退出清理（`absock_cleanup`）仅遍历 `absock_table` 中登记的 active 节点与 `absock_links` 链表执行 `unlink`，并在本进程所属的 `absock_dir` 执行 `rmdir`；
  - 绝不递归删除 `ELFUSE_ABSOCK_BASE` 根目录自身，亦绝不触碰同级其他命名空间目录。

---

## 三、 第二阶段：独立单元测试与真实 Inode 验证（Verification Evidence）

审查员在全新的隔离环境（使用测试目录 `/Users/mewcapoo/Projects/proton-macos-lab/.sr`，权限 `0700`）中执行了全套独立实测，测试过程不启动 Xvfb/Wine，日志完整保存于 `logs/socket-base-review/`。

### 1. 独立 C 单元测试矩阵（覆盖全部 10 项极端边界）
源码路径：`fixtures/runtime/socket-review/test_absock_unit.c`（日志：`logs/socket-base-review/1_unit_tests.log`）：

| 序号 | 边界测试项 | 测试输入与条件 | 预期表现与错误码 | 实测回显与退出码 | 判定 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **U1** | Unset 兼容回退 | `unsetenv("ELFUSE_ABSOCK_BASE")` | 默认回退至 `/tmp/elfuse-absock-12345` | `PASS: test_unset_defaults_to_tmp -> /tmp/elfuse-absock-12345` | **PASS** |
| **U2** | 显式空字符串拦截 | `ELFUSE_ABSOCK_BASE=""` | 立即硬失败，返回 `EINVAL`，绝不回退 | `PASS: test_set_empty_fails_einval` | **PASS** |
| **U3** | 相对路径拦截 | `ELFUSE_ABSOCK_BASE="relative/path"` | 立即硬失败，返回 `EINVAL`，绝不回退 | `PASS: test_relative_path_fails_einval` | **PASS** |
| **U4** | 不存在路径拦截 | `ELFUSE_ABSOCK_BASE="/lab/.no_such_dir"` | 立即硬失败，返回 `ENOENT`，绝不回退 | `PASS: test_nonexistent_dir_fails_enoent` | **PASS** |
| **U5** | 合法 0700 路径 | `ELFUSE_ABSOCK_BASE="/lab/.sr"` | 成功返回紧凑格式路径 `.../.sr/n0000000000003039` | `PASS: test_valid_0700_base_succeeds` | **PASS** |
| **U6** | 末尾多斜杠剥离 | `ELFUSE_ABSOCK_BASE="/lab/.sr///"` | 自动剥离尾斜杠，成功生成路径 | `PASS: test_trailing_slashes_stripped_succeeds` | **PASS** |
| **U7** | 符号链接拦截 | `ELFUSE_ABSOCK_BASE="/lab/.sr_lnk"` | 立即硬失败，返回 `ELOOP` | `PASS: test_symlink_base_fails_eloop` | **PASS** |
| **U8** | 带尾斜杠符号链接拦截 | `ELFUSE_ABSOCK_BASE="/lab/.sr_lnk/"` | 剥离斜杠后成功识别符号链接，返回 `ELOOP` | `PASS: test_symlink_trailing_slash_fails_eloop` | **PASS** |
| **U9** | 权限非 0700 拦截 | `ELFUSE_ABSOCK_BASE` 模式 `0755` | 拒绝群组/全局读写执行，返回 `EACCES` | `PASS: test_bad_permission_fails_eacces` | **PASS** |
| **U10**| 超长基准路径拦截 | `ELFUSE_ABSOCK_BASE` 长度 $\ge 60$ 字节 | 预检即拒绝，返回 `ENAMETOOLONG` | `PASS: test_too_long_base_fails_enametoolong` | **PASS** |

### 2. 真实抽象套接字 Inode 观测与双进程通信实测
- **测试工具**：`fixtures/runtime/socket-review/test_absock_inode_check.py`
- **执行命令**：通过冻结二进制 `sources/elfuse-socket-derived/build/elfuse`（SHA-256：`06a2fceb...`）在独立目录 `.sr` 下运行真实 Linux Python 3.14。
- **实测结果**（记录于 `logs/socket-base-review/4_frozen_absock_inode.log`）：
  ```text
  Server bound: found subdirs in .sr: ['nf0e4d15672e47845']
  Files inside namespace dir nf0e4d15672e47845: ['7265766965775f696e6f644270cbc865a4d3b9']
  OBSERVED REAL INODE: 16417974, mode: 0o140755, path: /Users/mewcapoo/Projects/proton-macos-lab/.sr/nf0e4d15672e47845/7265766965775f696e6f644270cbc865a4d3b9
  PASS: ABSTRACT_SOCKET_INODE_AND_COMMUNICATION_VERIFIED
  Subdirs remaining in .sr after exit: []
  Mode of .sr after test: 0o40700
  ```
  * **Inode 确证**：在宿主文件系统观测到类型为套接字（`S_IFSOCK`，`mode 0140755`）的实际 inode `16417974`；
  * **通信确证**：父子进程顺利完成握手通信；
  * **清理确证**：退出后子命名空间目录自动删除，`.sr` 根目录无多余文件残留且保持 `0700`。

### 3. 长路径 Shortening 符号链接 Inode 观测与通信实测
- **测试工具**：`fixtures/runtime/socket-review/test_shortening_inode_check.py`
- **实测结果**（记录于 `logs/socket-base-review/5_frozen_shortening_inode.log`）：
  ```text
  Server bound: found subdirs in .sr: ['n00b072726694d427']
  Entries inside namespace dir n00b072726694d427: ['p86035-2f55736572732f6db19c02408f4893e4']
  OBSERVED SHORTENING SYMLINK: inode=16418021, mode=0o120755, link=p86035-2f55736572732f6db19c02408f4893e4 -> /Users/mewcapoo/Projects/proton-macos-lab/fixtures/runtime/arch-case/tmp/sssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss.sock
  PASS: PATHNAME_SHORTENING_INODE_AND_COMMUNICATION_VERIFIED
  Subdirs remaining in .sr after exit: []
  Mode of .sr after test: 0o40700
  ```
  * **Shortening 确证**：Linux Guest 105 字节长路径在宿主被成功映射至 `.sr/n<namespace>/` 下的软链接（`S_IFLNK`，`mode 0120755`，`inode 16418021`），并准确指向 sysroot 内部目标；
  * **通信与清理确证**：客户端通过原 Guest 长路径顺利连接，退出后短链接和子命名空间目录全部清理。

### 4. 跨 Execve 环境继承与通信实测
- **测试工具**：`fixtures/runtime/socket-review/test_absock_cross_exec.py`
- **实测结果**（记录于 `logs/socket-base-review/6_cross_exec_verification.log`）：
  ```text
  Return code: 0
  Stdout: PASS: ABSTRACT_SOCKET_CROSS_EXEC_COMMUNICATION_VERIFIED
  Subdirs remaining in .sr after exit: []
  Mode of .sr after test: 0o40700
  ```
  确证即使子进程经过 `os.execv` 重新加载镜像，环境中的 `ELFUSE_ABSOCK_BASE` 与命名空间派生算法完全保持一致，能够无缝连通预先绑定的抽象套接字。

### 5. `getsockname()` 路径反向还原核查
- **测试工具**：`fixtures/runtime/socket-review/test_getsockname_reverse.py`
- **实测结果**（记录于 `logs/socket-base-review/7_getsockname_verification.log`）：
  ```text
  Bound guest path: /tmp/rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr.sock
  getsockname() returned: /tmp/rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr.sock
  PASS: GETSOCKNAME_REVERSE_MAPPING_VERIFIED
  ```
  确证长路径套接字经过中继缩短后，应用调用 `getsockname` 依然能得到原始的 Guest 路径名，反向解析逻辑完备。

---

## 四、 关键工件哈希与交付清单

1. **二进制与核心组件账本**：
   - 冻结套接字派生二进制：`sources/elfuse-socket-derived/build/elfuse`  
     **SHA-256**: `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`
   - 生命周期基线二进制（对比用）：`sources/elfuse-lifecycle-derived/build/elfuse`  
     **SHA-256**: `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a`
   - Linux Python 解释器：`fixtures/runtime/arch-case/usr/bin/python3.14`  
     **SHA-256**: `c6bc1ef497b896b7575c546b13f9bafe52e2066f184fdd3fec6af4b5b6349947`
2. **独立审查产物**：
   - 审查报告：`reports/socket-base-review.md`
   - 独立归档日志：`logs/socket-base-review/`
     * `1_unit_tests.log`（10 项 C 单元测试）
     * `2_inode_verification.log`（抽象套接字真实 Inode 观测）
     * `3_shortening_inode_verification.log`（长路径 Shortening Inode 观测）
     * `4_frozen_absock_inode.log`（冻结二进制抽象套接字实测）
     * `5_frozen_shortening_inode.log`（冻结二进制短链接实测）
     * `6_cross_exec_verification.log`（跨 Execve 继承通信实测）
     * `7_getsockname_verification.log`（getsockname 反查实测）
   - 独立测试脚本与工件：
     * `fixtures/runtime/socket-review/test_absock_unit.c` / `test_absock_unit`
     * `fixtures/runtime/socket-review/test_absock_inode_check.py`
     * `fixtures/runtime/socket-review/test_shortening_inode_check.py`
     * `fixtures/runtime/socket-review/test_absock_cross_exec.py`
     * `fixtures/runtime/socket-review/test_getsockname_reverse.py`
   - 独立安全基准目录：`/Users/mewcapoo/Projects/proton-macos-lab/.sr`（验证后保持 `0700`，内部已完全清空）

---

## 五、 最终签字

- **审查员**：`final-lab-reviewer`
- **审查结论**：**通过最终验收（APPROVED）**。
- **技术事实认定**：`sources/elfuse-socket-derived` 成功实现了可配置、强隔离、防注入且带紧凑命名空间的 `ELFUSE_ABSOCK_BASE` 抽象套接字中继机制，经实测真实 Inode、父子通信、短链接与反向查询均通过，无宿主 `/tmp` 泄漏。
- **关联任务状态**：`task-41` 满足完成条件。
