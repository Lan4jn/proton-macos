# 将 elfuse 抽象套接字中继显式限制到 lab 目录报告 (Task-40)

## 1. 任务背景与核心目标

在之前的 X11 / Xvfb 探索中，我们确认 Linux 下默认 X11 传输优先使用抽象 UNIX 套接字（Abstract UNIX Domain Sockets，首字节为 `\0`）。
在 `sources/elfuse` 原始实现中，`absock_dir_format` 硬编码为宿主系统目录 `/tmp/elfuse-absock-%llu`。这导致 Linux 客户端或服务一旦使用抽象套接字或超过 104 字符的长路径套接字，就会在宿主 `/tmp` 下创建中继文件，违反了“严禁污染宿主系统目录、文件完全限制在 lab 内部”的实验红线。

**本任务目标**：
在派生代码 `sources/elfuse-socket-derived`（基于通过生命周期验收的 `f2a678...` 基线）中，实现显式 opt-in 环境变量 `ELFUSE_ABSOCK_BASE`，支持将抽象套接字及长路径 shortening 中继重定向至 lab 私有安全目录（如 `lab/.s`，权限 0700）。
同时满足：
1. 默认 unset 时保持原有 `/tmp` 兼容行为，未设置时不改动旧逻辑；
2. 显式设置但无效（如相对路径、空字符串、不存在路径、world-writable、symlink、过长）时**必须硬失败并返回明确 errno**，**严禁静默 fallback 到 host `/tmp`**；
3. 保留安全检查，去除 trailing slash 避免绕过 symlink 检查；
4. 压缩子目录命名预算（`/n%016llx`，18字节），确保在 44 字节的 lab 基准路径下，加上 PID 前缀与 FNV-1a 哈希后，整体 `sun_path` 严格控制在 `< 104` 字节内；
5. 退出清理仅删除自己命名空间和持有的套接字/软链接，不触碰基准目录本身或他人命名空间。

---

## 2. 代码修改与实现设计

### 2.1 源码变更文件
- `sources/elfuse-socket-derived/src/syscall/net-absock.c`
- `sources/elfuse-socket-derived/src/syscall/net.c`

### 2.2 关键实现逻辑
1. **严格安全性校验 `absock_validate_custom_base`**:
   - 检查非空且首字符为 `/`（绝对路径）；空字符串或非绝对路径返回 `EINVAL`；
   - 长度上限设为 60 字节，超长返回 `ENAMETOOLONG`；
   - **去除末尾斜杠 (`/`) 后执行 `lstat`**：彻底堵住 macOS 下对带尾斜杠符号链接自动 follow 的内核行为漏洞；若为符号链接直接返回 `ELOOP`；
   - 检查 `S_ISDIR`，非目录返回 `ENOTDIR`；
   - 检查 `st.st_uid == getuid()` 且 `(st.st_mode & 077) == 0`（严禁 group/other 可读写执行），权限不符返回 `EACCES`。
2. **紧凑子命名空间格式 `absock_dir_format`**:
   - 当 `ELFUSE_ABSOCK_BASE` 显式设置时，校验成功后格式化为：
     `%s/n%016llx`（例如 `/Users/.../proton-macos-lab/.s/n0000000000001234`，仅占用 18 字节固定后缀）；
   - 相比原 `/elfuse-absock-%llu`（35 字节）大幅精简，即使加上 `p<pid>-<fnv1a>`（~24 字节），总路径长度仅约 `43 + 18 + 24 = 85 < 104`，留足 `sun_path` 余量；
   - 当格式化长度超出上限时返回 `ENAMETOOLONG`，绝不写入任何外部目录。
3. **真实 errno 传递 (`net.c`)**:
   - `sys_bind` 中若 `absock_bind_prepare` 返回负值，透传底层 `linux_errno()`，确保 `EACCES` / `ENOENT` / `ELOOP` / `ENAMETOOLONG` / `EINVAL` 能准确反馈给调用方，而非掩盖为通用的 `EINVAL`。
4. **退出清理安全性**:
   - 仅对进程自身注册的 active entries 及 minted links 调用 `unlink`；
   - 仅在所属子命名空间目录（`absock_dir`）内调用 `rmdir`，绝不删除 `ELFUSE_ABSOCK_BASE` 根目录或非自己所有的链接。

---

## 3. 组件身份与哈希账本

| 组件名称 | 文件路径 | SHA-256 哈希 | 状态 / 备注 |
| :--- | :--- | :--- | :--- |
| **elfuse baseline** | `sources/elfuse-lifecycle-derived/build/elfuse` | `f2a678dd74284b1a9e82c4270b2d12e4092006f8eb2f97046a6d4780bb0bca7a` | 冻结基线 (已通过独立生命周期验收) |
| **elfuse socket-derived** | `sources/elfuse-socket-derived/build/elfuse` | `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d` | 新增 `ELFUSE_ABSOCK_BASE` 支持，代码签名合格 |
| **Linux Python** | `fixtures/runtime/arch-case/usr/bin/python3.14` | `c6bc1ef497b896b7575c546b13f9bafe52e2066f184fdd3fec6af4b5b6349947` | 真实 aarch64 Linux Python 3.14.7 |
| **Lab 中继目录** | `/Users/mewcapoo/Projects/proton-macos-lab/.s` | N/A (目录) | 权限 `0700`，所有者 `mewcapoo:staff` |

---

## 4. 全套 TDD 与实测结果 (10/10 PASS)

通过受控 runner (`scripts/runtime/socket_base/run_socket_base_suite.py`) 运行 10 组全覆盖自动化实测，耗时严格控制在 10 秒以内：

| 编号 | 测试用例 ID | 测试场景与环境变量配置 | 预期行为与检测点 | 实际退出码 | 实测判定 |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **T1** | `T1_defaultcompat` | `ELFUSE_ABSOCK_BASE` 未设置 (unset) | 默认走 `/tmp/elfuse-absock-%llu`，双进程通信成功 | `0` | **PASS** |
| **T2** | `T2_explicitvalid` | `ELFUSE_ABSOCK_BASE=/lab/.s` (mode 0700) | 在 `.s/n<hex>/` 下建立 socket，通信成功，退出后自动清理子目录 | `0` | **PASS** |
| **T3** | `T3_invalidrelative` | `ELFUSE_ABSOCK_BASE=".s"` (相对路径) | 拦截相对路径，返回 `EINVAL` (Invalid argument)，无 fallback | `3` (err 22) | **PASS** |
| **T4** | `T4_setempty` | `ELFUSE_ABSOCK_BASE=""` (显式空字符串) | 拦截显式空值，返回 `EINVAL` (Invalid argument)，无 fallback | `3` (err 22) | **PASS** |
| **T5** | `T5_nonexistent` | `ELFUSE_ABSOCK_BASE=/tmp/nonexistent_xyz` | 拦截不存在目录，返回 `ENOENT` (No such file or directory) | `3` (err 2) | **PASS** |
| **T6** | `T6_worldwritable` | `ELFUSE_ABSOCK_BASE=/lab/.s_world_test` (0777) | 拦截全局可读写目录，返回 `EACCES` (Permission denied) | `3` (err 13) | **PASS** |
| **T7** | `T7_symlinkbase` | `ELFUSE_ABSOCK_BASE=/lab/.s_symlink` (及带尾斜杠 `/`) | 拦截符号链接（含带尾斜杠变体），返回 `ELOOP` (Too many levels of symlinks) | `3` (err 40) | **PASS** |
| **T8** | `T8_toolong` | `ELFUSE_ABSOCK_BASE` 路径长度 100 字节 ($\ge 60$) | 拦截超长基路径，返回 `ENAMETOOLONG` (File name too long) | `3` (err 36) | **PASS** |
| **T9** | `T9_pathname_shortening` | Guest 长套接字路径 105 字节（在宿主达 150 字节） | 触发 `absock_shorten_path`，在 `.s/n<hex>/` 下生成短链接通信成功 | `0` | **PASS** |
| **T10** | `T10_no_host_tmp_leak` | 审计显式设置 `ELFUSE_ABSOCK_BASE` 时宿主 `/tmp` 状态 | 确证无任何新目录或套接字泄漏到宿主 `/tmp` | N/A | **PASS** |

---

## 5. 源码完整 Diff

```diff
--- sources/elfuse-lifecycle-derived/src/syscall/net-absock.c
+++ sources/elfuse-socket-derived/src/syscall/net-absock.c
@@ -82,13 +82,92 @@ static int absock_link_count;
 
 static void absock_cleanup(void);
 
+/* Check whether a custom base directory specified via ELFUSE_ABSOCK_BASE is secure.
+ * Must be an absolute path, not a symlink (including when specified with a trailing slash),
+ * owned by getuid(), mode user-only (no group or other permissions).
+ * Returns 0 on success, or -1 with errno set:
+ *   EINVAL: not absolute, or empty string
+ *   ENOENT / ENOTDIR / EACCES: path lookup or permission violation
+ *   ELOOP: symlink detected
+ *   ENAMETOOLONG: total path would exceed sun_path budget
+ */
+static int absock_validate_custom_base(const char *base, char *clean_out, size_t clean_sz)
+{
+    if (!base || base[0] != '/') {
+        errno = EINVAL;
+        return -1;
+    }
+
+    size_t len = strlen(base);
+    if (len == 0 || len >= 60) {
+        errno = (len >= 60) ? ENAMETOOLONG : EINVAL;
+        return -1;
+    }
+
+    /* Strip any trailing slashes FIRST so lstat inspects the leaf link itself,
+     * not the link target (macOS lstat on a path with a trailing slash follows symlinks!).
+     */
+    size_t blen = len;
+    while (blen > 1 && base[blen - 1] == '/')
+        blen--;
+
+    if (blen >= clean_sz) {
+        errno = ENAMETOOLONG;
+        return -1;
+    }
+    memcpy(clean_out, base, blen);
+    clean_out[blen] = '\0';
+
+    struct stat st;
+    if (lstat(clean_out, &st) < 0)
+        return -1;
+
+    if (S_ISLNK(st.st_mode)) {
+        errno = ELOOP;
+        return -1;
+    }
+
+    if (!S_ISDIR(st.st_mode)) {
+        errno = ENOTDIR;
+        return -1;
+    }
+
+    if (st.st_uid != getuid() || (st.st_mode & (S_IRWXG | S_IRWXO)) != 0) {
+        errno = EACCES;
+        return -1;
+    }
+
+    return 0;
+}
+
 /* Spell the namespace directory for @namespace_id. Shared so a reader can name
  * the directory without depending on this process being the one that created
  * it, which is not the same thing: fork spawns a fresh process that inherits
  * the id and reads back sockaddrs pointing into the shared dir.
+ *
+ * If ELFUSE_ABSOCK_BASE is set (including set-empty), validates it strictly.
+ * An invalid or set-empty base fails immediately with errno without fallback to /tmp.
+ * To preserve ample sun_path budget (< 104) for PID prefixes and FNV-1a digests,
+ * custom base uses the compact sub-directory format "/n%016llx" (18 bytes).
+ * Only an unset env defaults to /tmp with the legacy "/tmp/elfuse-absock-%llu".
  */
 static int absock_dir_format(char *out, size_t out_sz, uint64_t namespace_id)
 {
+    const char *custom_base = getenv("ELFUSE_ABSOCK_BASE");
+    if (custom_base) {
+        char clean_base[64];
+        if (absock_validate_custom_base(custom_base, clean_base, sizeof(clean_base)) < 0)
+            return -1;
+
+        int n = snprintf(out, out_sz, "%s/n%016llx",
+                         clean_base, (unsigned long long) namespace_id);
+        if (n < 0 || (size_t) n >= out_sz || (size_t) n > 72) {
+            errno = ENAMETOOLONG;
+            return -1;
+        }
+        return n;
+    }
+
     return snprintf(out, out_sz, "/tmp/elfuse-absock-%llu",
                     (unsigned long long) namespace_id);
 }
@@ -111,7 +190,8 @@ static int absock_ensure_dir_locked(void)
         return create_private_dir(absock_dir);
     }
 
-    absock_dir_format(absock_dir, sizeof(absock_dir), namespace_id);
+    if (absock_dir_format(absock_dir, sizeof(absock_dir), namespace_id) < 0)
+        return -1;
 
     /* The namespace-id path is guessable; create_private_dir rejects a
      * pre-planted symlink or foreign-owned directory in world-writable /tmp.

--- sources/elfuse-lifecycle-derived/src/syscall/net.c
+++ sources/elfuse-socket-derived/src/syscall/net.c
@@ -549,7 +549,7 @@ int64_t sys_bind(guest_t *g, int fd, uint64_t addr_gva, uint32_t addrlen)
         }
         if (absock_idx < 0) {
             host_fd_ref_close(&host_ref);
-            return -LINUX_EINVAL;
+            return linux_errno();
         }
         mac_len = bind_len;
     } else {
```

---

## 6. 证据产物汇总

- **修改后源码目录**: `sources/elfuse-socket-derived/`
- **签名可执行文件**: `sources/elfuse-socket-derived/build/elfuse` (SHA-256: `06a2fceb45152418af82bd620fca9d6a075bd138461142e001b118d1b336551d`)
- **测试套件运行器**: `scripts/runtime/socket_base/run_socket_base_suite.py`
- **套接字探测脚本**:
  - `fixtures/runtime/socket-base/test_absock_comm.py` (抽象套接字双进程通信)
  - `fixtures/runtime/socket-base/test_shortening_comm.py` (长路径 shortening 通信)
- **测试结构化结果日志**: `logs/socket-base/socket_base_test_results.json`
- **技术报告**: `reports/socket-base.md`
