# 官方发布资产补查（round10）

本轮不重试已知匿名 SteamCMD `No subscription`，也不将源码归档冒充运行时二进制。

- 查询地址：`https://api.github.com/repos/ValveSoftware/Proton/releases?per_page=3`，通过HTTPS、GitHub JSON API读取，未使用账号或token。
- 实际返回三个tag：`proton-11.0-2e`、`proton-11.0-2`、`proton-11.0-1b`。
- 三个release的`assets`数组均为空；各有`tarball_url`，其为源码tarball地址，不是完整ARM64 Proton运行时。
- 官方网页`https://github.com/ValveSoftware/Proton/releases`的页面提取显示“Assets2”，但API明确没有上传的release asset；网页计数不可直接当二进制下载证据。
- 本次有限查询未发现由Valve GitHub release直接托管的ARM64运行时包；不证明所有tag、Steam渠道或其它官方渠道均无此包。
- 现有398113534字节公开seed仍来自The412Banner/winlator-contents，SHA及原脚本一致性已验，但独立Valve签名/Steam清单内容真实性仍未认证，不因最新官方更新日志提及FEX/ARM64而升级来源置信度。
- 未下载新运行时、未替换现有Proton、未变更真实Steam或全局环境。
