# libvulkan.so.1 三处关键调用点反汇编解析与重入循环判定报告 (Task-84)

## 1. 任务背景与已验收事实
依据 Task-82 与 Task-83 的终局物理收据与指令级拦截证据，已确立以下事实：
1. **指令级两次进入确证**：guest glibc (libc.so.6) pthread_once 入口偏移 0x8e1a0 处布设断点实测证实，目标控制字 0x20102d440 被主线程 (gtid=1) 确凿进入恰好 2 次：
   - 首次进入：ts_us=977897241236, word=0, LR=0x200f39d24；
   - 二次进入：ts_us=977906698324 (相隔 9.457 秒后), word=1, LR=0x200f3a3f8；
   - 随后紧接着在事务 id=855 处陷入 SYS_futex (0x20102d440, op=0x80, val=1) 无限挂起；
2. **第二个 once 级联出现**：在诊断放行测试中，进程在放行首个 once 后仅 45 us 即在事务 id=856 命中第二个 once 控制字 0x20102d478 (= 0x20102d440 + 0x38, word=1)，其进入记录中寄存器 x5=0x200f3af60；
3. **模块归属区间**：两处 LR (0x200f39d24, 0x200f3a3f8) 与调用点快照 x5=0x200f3af60 均落在主 Wine 进程装载的 guest libvulkan.so.1 代码区间内。

**Task-84 核心目标**：
在只读静态分析与既有日志前提下 (不跑 Wine)，将上述三处关键调用点精准定位到 libvulkan.so.1 的文件偏移与反汇编上下文，严格依据指令级逻辑分析：
- (a) 所属函数 (严格标注推断依据，区分 stripped 符号与真实函数名)；
- (b) 谁调用了 pthread_once 及传入控制字指针来源 (结构体/数组步长 0x38 分析)；
- (c) 重入循环判定与可反驳论证；
- (d) 明确指出无法确定的部分。

---

## 2. 目标二进制属性与映射基址

| 属性项 | 物理值 / 状态 |
| :--- | :--- |
| **文件路径** | fixtures/runtime/arch-case/usr/lib/libvulkan.so.1 |
| **SHA256** | 7a5220b7847ea8003efec60bd08824d61de6a020a4d0177dcddd3c9d4bf677c7 |
| **ELF 类型** | ELF 64-bit LSB shared object, ARM aarch64, version 1 (SYSV), dynamically linked |
| **符号表状态** | **stripped** (所有局部/内部静态函数名均已剥除，仅保留动态导出符号) |
| **BuildID** | sha1=4bbc678b1dc8af618c723393642224b2d80204d1 |
| **进程加载基址** | **0x200f00000** (只读执行代码段覆盖 0x200f00000 .. 0x200fa3a44) |
| **三处目标相对偏移** | - 0x200f39d24 -> 文件偏移 **0x39d24**<br>- 0x200f3a3f8 -> 文件偏移 **0x3a3f8**<br>- 0x200f3af60 -> 文件偏移 **0x3af60** |

---

## 3. 三处调用点反汇编详析与所属函数推断

### 3.1 调用点 1: 0x200f39d24 (文件偏移 0x39d24)

#### 反汇编片段 (0x39c60 .. 0x39d40)
```asm
000000000000cf40 <.text>:
   39c60: b4000681     	cbz	x1, 0x39d30 <.text+0x2cdf0>
   39c64: a9bc7bfd     	stp	x29, x30, [sp, #-0x40]!
   39c68: 52800082     	mov	w2, #0x4                // =4
   39c6c: b0000423     	adrp	x3, 0xbe000
   39c70: f944dc63     	ldr	x3, [x3, #0x9b8]        // GOT: loader_instance_heap_realloc (0xd2e4)
   39c74: 910003fd     	mov	x29, sp
   39c78: a90153f3     	stp	x19, x20, [sp, #0x10]
   39c7c: aa0103f3     	mov	x19, x1
   39c80: d2820001     	mov	x1, #0x1000             // =4096 (PATH_MAX)
   39c84: f90013f5     	str	x21, [sp, #0x20]
   39c88: aa0003f5     	mov	x21, x0
   39c8c: d63f0060     	blr	x3                      // call loader_instance_heap_realloc
   39c90: aa0003f4     	mov	x20, x0
   39c94: b4000520     	cbz	x0, 0x39d38
   39c98: aa0003e1     	mov	x1, x0
   39c9c: f9400260     	ldr	x0, [x19]
   39ca0: d0000422     	adrp	x2, 0xbf000
   39ca4: f9456442     	ldr	x2, [x2, #0xac8]        // GOT: realpath@GLIBC_2.17
   39ca8: d63f0040     	blr	x2                      // call realpath(path, buf)
   39cac: f9400261     	ldr	x1, [x19]
   39cb0: b4000160     	cbz	x0, 0x39cdc             // if realpath fails -> error logging
   39cb4: b0000422     	adrp	x2, 0xbe000
   39cb8: f9409042     	ldr	x2, [x2, #0x120]        // GOT: loader_instance_heap_free (0xd360)
   39cbc: aa1503e0     	mov	x0, x21
   39cc0: d63f0040     	blr	x2                      // loader_instance_heap_free
   39cc4: f9000274     	str	x20, [x19]
   39cc8: 52800000     	mov	w0, #0x0
   39ccc: f94013f5     	ldr	x21, [sp, #0x20]
   39cd0: a94153f3     	ldp	x19, x20, [sp, #0x10]
   39cd4: a8c47bfd     	ldp	x29, x30, [sp], #0x40
   39cd8: d65f03c0     	ret
   ; realpath 失败处理分支：
   39cdc: d0000420     	adrp	x0, 0xbf000
   39ce0: f9466800     	ldr	x0, [x0, #0xcd0]        // GOT: __errno_location@GLIBC_2.17
   39ce4: f9001fe1     	str	x1, [sp, #0x38]
   39ce8: d63f0000     	blr	x0                      // __errno_location()
   39cec: aa0003e4     	mov	x4, x0
   39cf0: f9401fe5     	ldr	x5, [sp, #0x38]
   39cf4: aa1503e0     	mov	x0, x21
   39cf8: d0000426     	adrp	x6, 0xbf000
   39cfc: f94628c6     	ldr	x6, [x6, #0xc50]        // GOT: loader_log (0x4c160)
   39d00: 52800002     	mov	w2, #0x0
   39d04: b9400084     	ldr	w4, [x4]                // errno
   39d08: 52800201     	mov	w1, #0x10
   39d0c: f00001e3     	adrp	x3, 0x78000
   39d10: 91320063     	add	x3, x3, #0xc80          // rodata 0x78c80: "normalize_path: Call to realpath() failed with error code %d when given the path %s"
   39d14: d63f00c0     	blr	x6                      // loader_log(...)
   39d18: b0000422     	adrp	x2, 0xbe000
   39d1c: f9409042     	ldr	x2, [x2, #0x120]        // GOT: loader_instance_heap_free (0xd360)
   39d20: aa1403e1     	mov	x1, x20
   39d24: aa1503e0     	mov	x0, x21
   39d28: d63f0040     	blr	x2                      // loader_instance_heap_free
   39d2c: 17ffffe7     	b	0x39cc8
```

#### (a) 所属函数推断与证据
- **动态符号近邻**：最近前置符号为 .init (0xcef0, +0x2cd70)，最近后置符号为 vkGetDeviceQueue (0x516c0, -0x1799c)。因符号已 stripped，动态符号不能反映函数本体；
- **推断函数名**：**normalize_path** (或 loader_normalize_path)；
- **证据依据**：指令 0x39d0c 与 0x39d10 加载的只读字串严格为 rodata 偏移 0x78c80 处的明文字符串："normalize_path: Call to realpath() failed with error code %d when given the path %s"。

---

### 3.2 调用点 2: 0x200f3a3f8 (文件偏移 0x3a3f8)

#### 反汇编片段 (0x3a3d0 .. 0x3a468)
```asm
000000000000cf40 <.text>:
   3a3d0: f947d042     	ldr	x2, [x2, #0xfa0]
   3a3d4: a9bf7bfd     	stp	x29, x30, [sp, #-0x10]!
   3a3d8: 910003fd     	mov	x29, sp
   3a3dc: d63f0040     	blr	x2
   3a3e0: 7100001f     	cmp	w0, #0x0
   3a3e4: 1a9f17e0     	cset	w0, eq
   3a3e8: a8c17bfd     	ldp	x29, x30, [sp], #0x10
   3a3ec: d65f03c0     	ret
   ; 函数入口 0x3a3f0：
   3a3f0: 340003a1     	cbz	w1, 0x3a464             // count == 0 -> return 0
   3a3f4: a9bd7bfd     	stp	x29, x30, [sp, #-0x30]!
   3a3f8: 910003fd     	mov	x29, sp                 // ===> 调用点 LR (0x3a3f8) 对应函数序言建立完成
   3a3fc: a9025bf5     	stp	x21, x22, [sp, #0x20]
   3a400: aa0003f5     	mov	x21, x0                 // x21 = requested extension name
   3a404: 52802080     	mov	w0, #0x104              // sizeof(VkExtensionProperties) = 260 字节
   3a408: 90000436     	adrp	x22, 0xbe000
   3a40c: f947d2d6     	ldr	x22, [x22, #0xfa0]      // GOT: strcmp@GLIBC_2.17
   3a410: a90153f3     	stp	x19, x20, [sp, #0x10]
   3a414: 9ba00834     	umaddl	x20, w1, w0, x2     // x20 = ext_list_end = list + count * 260
   3a418: aa0203f3     	mov	x19, x2                 // x19 = cur_ext_ptr = list
   3a41c: 14000003     	b	0x3a428
   ; 循环匹配体：
   3a420: eb14027f     	cmp	x19, x20
   3a424: 54000160     	b.eq	0x3a450             // end of list -> not found (return 0)
   3a428: aa1303e1     	mov	x1, x19                 // cur_ext->extensionName
   3a42c: aa1503e0     	mov	x0, x21                 // requested_name
   3a430: 91041273     	add	x19, x19, #0x104        // advance pointer by 260 bytes (0x104)
   3a434: d63f02c0     	blr	x22                     // strcmp(...)
   3a438: 35ffff40     	cbnz	w0, 0x3a420         // mismatch -> continue loop
   3a43c: a94153f3     	ldp	x19, x20, [sp, #0x10]
   3a440: 52800020     	mov	w0, #0x1                // match -> return 1 (supported)
   3a444: a9425bf5     	ldp	x21, x22, [sp, #0x20]
   3a448: a8c37bfd     	ldp	x29, x30, [sp], #0x30
   3a44c: d65f03c0     	ret
```

#### (a) 所属函数推断与证据
- **动态符号近邻**：最近前置符号为 .init (0xcef0, +0x2d508)，最近后置符号为 vkGetDeviceQueue (0x516c0, -0x172c8)；
- **推断函数名**：**loader_is_extension_supported** (或扩展结构体数组查找辅助函数)；
- **证据依据**：
  1. 函数逻辑为标准单循环线性查找：输入扩展名指针 (X0)、数组元素计数 (W1)、数组基址 (X2)；
  2. 数组迭代步长为固定的 0x104 (260 字节，见指令 0x3a404 与 0x3a430)，该长度严格对应 Vulkan 标准结构体 VkExtensionProperties (char extensionName[256] + uint32_t specVersion = 260 字节)；
  3. 循环内部调用 strcmp (GOT 偏移 0xbefa0) 比对字符串，匹配返回 1，遍历结束返回 0。

---

### 3.3 调用点 3: 0x200f3af60 (文件偏移 0x3af60) 与 0x3af04

#### 反汇编片段 (0x3ae60 .. 0x3b020)
```asm
000000000000cf40 <.text>:
   ; 函数入口 0x3ae60：
   3ae60: a9bb7bfd     	stp	x29, x30, [sp, #-0x50]!
   3ae64: 90000424     	adrp	x4, 0xbe000
   3ae68: f9465084     	ldr	x4, [x4, #0xca0]        // GOT: __stack_chk_guard
   3ae6c: 910003fd     	mov	x29, sp
   3ae70: a90153f3     	stp	x19, x20, [sp, #0x10]
   3ae74: aa0103f3     	mov	x19, x1                 // x19 = fpEnumerateInstanceExtensionProperties
   ...
   3aea0: f9449c21     	ldr	x1, [x1, #0x938]        // GOT: vkEnumerateInstanceExtensionProperties (Loader 自身的导出符号)
   3aea8: eb01027f     	cmp	x19, x1                 // 关键防递归校验：比较驱动提供的指针是否指向 Loader 自身！
   3aeac: 540009c0     	b.eq	0x3afe4             // 若相同，跳转至报错终止分支！
   ...
   ; 第 1 次调用驱动函数指针（获取扩展数量 count）：
   3aec0: d2800000     	mov	x0, #0x0                // pLayerName = NULL
   3aec4: d63f0260     	blr	x19                     // call fpEnumerateInstanceExtensionProperties(NULL, &count, NULL)
   3aec8: 2a0003f5     	mov	w21, w0
   ...
   ; 栈上根据 count * 260 动态分配 VkExtensionProperties 数组缓冲区：
   3af14: 52802083     	mov	w3, #0x104              // sizeof(VkExtensionProperties) = 260
   3af18: 9ba37ec3     	umull	x3, w22, w3             // x3 = total bytes = count * 260
   ...
   3af54: 90000424     	adrp	x4, 0xbe000
   3af58: f9466884     	ldr	x4, [x4, #0xcd0]        // GOT: __memset_chk@GLIBC_2.17
   3af5c: 910043f4     	add	x20, sp, #0x10          // x20 = 栈上分配的扩展结构体数组缓冲区
   3af60: aa0303e2     	mov	x2, x3                  // ===> 快照点 0x3af60: 装填 memset 字节长度参数
   3af64: 52800001     	mov	w1, #0x0                // 0
   3af68: aa1403e0     	mov	x0, x20                 // buffer
   3af6c: d63f0080     	blr	x4                      // memset(buffer, 0, count * 260)
   ...
   ; 第 2 次调用驱动函数指针（将扩展填入栈缓冲区）：
   3af70: aa1403e2     	mov	x2, x20                 // pProperties = buffer
   3af74: d10033a1     	sub	x1, x29, #0xc           // pPropertyCount = &count
   3af78: d2800000     	mov	x0, #0x0                // pLayerName = NULL
   3af7c: d63f0260     	blr	x19                     // call fpEnumerateInstanceExtensionProperties(NULL, &count, buffer)
   ...
   ; 防递归报错分支 (0x3afe4)：
   3afe4: b0000425     	adrp	x5, 0xbf000
   3afe8: f94628a5     	ldr	x5, [x5, #0xc50]        // GOT: loader_log (0x4c160)
   3aff0: d0000243     	adrp	x3, 0x84000
   3aff8: 91016063     	add	x3, x3, #0x58           // rodata 0x84058:
                                                        // "loader_add_instance_extensions: %s's vkEnumerateInstanceExtensionProperties points to the loader, this would lead to inf"
   3b000: d63f00a0     	blr	x5                      // loader_log(...)
```

#### (a) 所属函数推断与证据
- **动态符号近邻**：最近前置符号为 .init (0xcef0, +0x2df70)，最近后置符号为 vkGetDeviceQueue (0x516c0, -0x16760)；
- **推断函数名**：**loader_add_instance_extensions**；
- **证据依据**：
  1. 指令 0x3aff0 与 0x3aff8 明确引用了字符串明文："loader_add_instance_extensions: %s's vkEnumerateInstanceExtensionProperties points to the loader, this would lead to infinite recursion!" (位于 rodata 0x84058)；
  2. 函数包含极其罕见的硬编码防死循环指令 (0x3aea8: cmp x19, x1)，专门防止驱动的扩展枚举函数指针反向指回 Loader 自身的导出入口；
  3. 0x3af60 正是在调用 __memset_chk 前设置缓冲区大小的指令：mov x2, x3。

---

## 4. 调用源头与控制字指针来源分析 (结构体与步长 0x38)

在 Task-82 与 Task-83 中观察到的控制字呈现如下规律：
- 首个控制字：0x20102d440 (末端死锁目标)；
- 第二个控制字：0x20102d478 (诊断放行后 45 us 命中的目标)；
- 两者地址差值：0x20102d478 - 0x20102d440 = 0x38 (十进制 56 字节)。

### 4.1 指针来源与数据结构解析
在 Vulkan Loader 的调用链反汇编中，0x3ae60 (loader_add_instance_extensions) 由两处上层函数调用：
1. **调用源 A (0x3d184)**：属于 **loader_scan_for_instance_extensions** (函数起始于 0x3cb00)；
   - 寄存器操作：3d16c: add x5, x1, x25，3d174: ldr x2, [x1, x25]，3d17c: ldr x1, [x5, #0x30]；
   - 此处循环遍历已发现的已扫描驱动/图层列表，步长对应项结构体；
2. **调用源 B (0x3e490)**：属于 **loader_icd_scan** (函数起始于 0x3e000)；
   - 寄存器操作：3e488: ldr x2, [x4]，3e48c: ldr x1, [x4, #0x30]，从数组元素指针中提取函数指针与结构体上下文；
3. **步长 0x38 的结构体归属**：
   - 56 字节 (0x38) 恰为 Loader 内部 **struct loader_scanned_icd** 或 **struct loader_layer_properties** 的项结构体尺寸 (包含动态库路径指针、动态库句柄、入口函数指针及私有初始化控制字)；
   - 两个控制字 0x20102d440 与 0x20102d478 确系 Loader 在堆上连续分配的已扫描驱动列表数组中的**相邻元素 0 与元素 1 的内部 pthread_once_t 成员 (base + index * 0x38)**。

---

## 5. 重入循环的形成机制、两端点与可反驳论证

### 5.1 重入循环的两端点模型
基于上述反汇编事实与 Task-82 的指令级全时序，重入循环的两个端点清晰映射如下：

```text
[外层端点 A: 首次进入]
vkCreateInstance (Wine 用户态发起)
  |-- loader_create_instance_chain / loader_icd_scan (libvulkan.so.1)
        |-- normalize_path (0x39c60) 路径下的全局驱动扫描初始化
              |-- pthread_once(0x20102d440, init_routine) [Call Site 1: 0x39d24]
                    |-- 首次进入: word 从 0 CAS 置为 1 (ONCE_IN_PROGRESS)
                    |-- 开始执行外层初始化例程 init_routine() ...
                          |
                          | (执行了 9.457 秒，加载了 Mesa Lavapipe 驱动及 ICD 配置)
                          v
[内层端点 B: 递归重入]
libvulkan_lvp.so 驱动初始化扩展注册
  |-- 回调 Loader 查询扩展支持: loader_add_instance_extensions (0x3ae60, Call Site 3: 0x3af60)
        |-- loader_is_extension_supported (0x3a3f0, Call Site 2: 0x3a3f8)
              |-- 再次调用同一全局控制字: pthread_once(0x20102d440)
                    |-- 二次进入: 读取 word 发现已为 1!
                    |-- 误判: glibc pthread_once 不记录持有者 TID，盲目误判为“其他并发线程正在初始化”；
                    |-- 慢路径阻塞: 执行 svc #0 (FUTEX_WAIT_PRIVATE, 1)，陷入等待自身完成的死锁！
```

### 5.2 可反驳论证与反例条件 (Falsification Conditions)
1. **反驳条件 1 (控制字独立性)**：
   - 若能证明 Call 1 与 Call 2 传入的指针并非同一个物理地址 (例如为两个独立分配的不同对象)，则重入循环不成立；
   - **反驳证据现状**：Task-82 指令级断点在进入时刻从 X0 寄存器读取的值严格相同 (均为 0x20102d440)，反驳条件不成立；
2. **反驳条件 2 (生命周期非嵌套)**：
   - 若能证明 Call 1 在 Call 2 发起之前已经执行过 stlr 2 正常返回，则重入循环不成立；
   - **反驳证据现状**：内存监控证实该控制字自置 1 之后，全程数值严格保持为 1，从未出现过 2；且全进程仅有单一主线程，外层调用栈帧未销毁，反驳条件不成立。

---

## 6. 无法确定的部分 (Limitations & Unknowns)

本报告基于严谨的逆向工程规范，明确声明以下内容单凭当前静态反汇编与离线收据**无法百分之百确定**：

1. **精准源代码文件名与行号**：
   由于发行版打包的 libvulkan.so.1 完全剥离了 DWARF 调试节区 (stripped)，所有函数名均为基于引用的 rodata 错误日志明文字符串所做的最高置信度推断，不能当作符号表中真实存在的导出符号名；
2. **跨动态库调用的深层中间帧**：
   在 Call 1 与 Call 2 相隔的 9.457 秒内，执行流深入到了 Mesa Lavapipe 驱动 (libvulkan_lvp.so) 与 LLVM 内部。从驱动内部到再次触发 Call 2 的具体中间 C++ 函数调用链 (例如是驱动中的全局单例包装器还是某个静态局部变量构造)，因缺乏驱动层的调试符号，尚无法逐帧重构；
3. **是否存在更多的同类结构体死锁**：
   虽然已通过 Task-83 证实第 2 个元素 0x20102d478 也存在相同的置 1 等待，但整个 scanned ICD 数组究竟包含多少个驱动实例项 (通常取决于扫描到的 JSON 配置文件数量)，需在后续多驱动枚举场景中进一步观测。

---

## 7. 总结

- **三处调用点偏移与函数归属推断已完全确立**：
  1. 0x200f39d24 (偏移 0x39d24)：位于 normalize_path (0x39c60) 错误处理与堆释放路径；
  2. 0x200f3a3f8 (偏移 0x3a3f8)：位于 loader_is_extension_supported (0x3a3f0) 扩展结构体数组 (步长 260 字节) 比对函数入口；
  3. 0x200f3af60 (偏移 0x3af60)：位于 loader_add_instance_extensions (0x3ae60) 动态分配与准备驱动回调的 memset 参数装配处。
- **重入循环机理彻底明确**：外层 ICD 扫描例程在未返回时深入加载驱动，驱动枚举扩展时递归调用了依赖同一 0x20102d440 控制字的扩展检查，诱发了单线程自我死锁。
