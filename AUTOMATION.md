# Windows 受控自动化试点 / Controlled automation pilot

本功能默认关闭。它与既有只读 maintenance 定时任务、普通 MCP 会话分别管理。此代码交付不表示真实频道发布或长期授权已验收。

## 前置条件

- Windows 开机且用户已登录、网络正常、Codex 已使用客户自己的账号登录；安装 Python 3.10+、ffmpeg/ffprobe 和工具包依赖。
- 公司已配置正式可用的 Google Desktop OAuth 项目，完成适用的 OAuth 验证与 YouTube 发布限制核验。没有配置时不要自造凭据或用别人的项目。
- 当前服务器已运行数据库迁移且显式启用 MCP_AUTOMATION_ENABLED。账户页面未启用时不能运行本功能。
- 先在账户规则中确定完整内容范围，保存当前版本；样片和执行预算由客户明确确认。

## 配对与授权

1. 在 ThinkNova 账户 MCP 页面绑定设备，取得仅本次显示的 telemetry_token；不要发给 AI、客服邮件或写入 memory。
2. 填写当前设备、实际 YouTube channel ID、每日积分预算、发布时间和 IANA 时区，确认后创建授权。取得仅本次显示的 execution_token。默认每日一条、期限30天，无预算无法启用。
3. 使用 .venv Python 运行 `python automation.py pair`，在隐藏提示中分别输入上述凭据；只保存 Windows 当前用户 DPAPI 密文。配对不会启动任务。
4. 从账户页面取得公司 Desktop OAuth 配置，按现有 YouTube 工具包说明保存为 publish/youtube/oauth_client.json；该原生客户端配置不含公司机密 Web 客户端秘密，不能替代客户频道授权。
5. 运行 `python automation.py youtube-auth`，客户本人在浏览器选择频道并授权。该流程保存为本机 DPAPI 密文，普通手工工具包原有 token.json 不会被覆盖或删除。
6. 首次实际生成/发布测试需要具体测试账户、频道、预算和内容授权。测试通过后，客户确认执行 `python automation.py install --user-confirmed`。它创建每5分钟检查一次的本机计划；不会把凭据或 Windows 密码写入任务参数。
7. 需要停止本机触发时运行 `python automation.py uninstall`；需要阻断服务调用时在账户页暂停/撤销授权或撤销设备。监控开关只关闭体检保存和通知，不等同暂停已启用的制作计划。

## 运行边界

- Codex 只输出符合 schema 的内容方案；程序验证后执行固定的任务、制作和发布动作，不执行方案中的 shell 命令。Codex 的使用额度由客户 Codex 账户负责，不能当作 ThinkNova 积分。
- 同一账号/频道/日期最多一个自动实例；更换授权也不会当日重复排一条。跨日恢复仅领取当天计划。
- 已建任务的网络重试复用 run/shot 请求号；终态失败进入待用户处理，不自动收费重抽。
- 视频采用现有默认能力生成，不能承诺固定原生分辨率、时长、台词或人物绝对一致。当前试点最多四镜，不代表已有通用长片自动导演能力。
- 发布前检查频道与成片；自动上传先以 private 暂存，取得任务回执、验证声明和再次核查授权后才转为 public。若授权被撤销或回读不明，保持待处理，不能盲目再次上传。
- `job.json.receipt.json` 在上传前写入。出现 uploading/uploaded 而未 verified，可能已经产生素材或作品；必须核对频道和 video_id，不得删除标记来重试。
- 私有暂存与公共发布都会操作真实 YouTube 账户；初次端到端验收不得用真实发布试错。
- 本地状态位于 `%LOCALAPPDATA%/ThinkNova/automation`，不进入 Git 或下载 ZIP。运行及发布记录应写入本地 memory；服务器只收脱敏状态、ID和摘要。
- 无网络/电脑关闭时服务器标记离线，而不是授权过期。心跳每15分钟、完整本机体检每小时一次；恢复网络后上报真实状态，不能编造离线期间的成功记录。

## 尚需外部验收

真实 Codex 非交互登录兼容、公司 OAuth 审核、YouTube AI 声明回读、实际频道公开发布、次日运行、休眠恢复及30天授权观察，均必须单独保留证据。不能把模拟 API 测试写成真实发布成功。

## English summary

This opt-in pilot requires a logged-on Windows user, network access, authenticated Codex and company-provisioned Google desktop OAuth configuration. Bind the device and grant an explicit channel/rules/daily-budget authorization in ThinkNova, then pair through hidden local prompts. Tokens stay in current-user DPAPI storage. Run youtube-auth, complete an authorized real-account acceptance test, then install --user-confirmed. Monitoring and execution are separate controls. Code-generated content plans cannot supply commands. Upload attempts are durable and stage privately before authorization/readback checks and public release; unknown outcomes require reconciliation, not re-upload. No cross-day backlog or automatic paid terminal retries. Real deployment and 30-day authorization remain external acceptance gates.


## 2026-11-05 分期升级 / Staged upgrade

- Mac 增加 LaunchAgent 与 Keychain 实现；Windows 保留任务计划与 DPAPI。Mac 的 marker 文件不含秘密；Keychain 授权可能需要用户在本机确认。实现不等于实机验收通过，默认不开启。
- 独立 monitoring.py pair / install --user-confirmed 不需要无人值守授权，只允许设备心跳；账户页可关闭监控和撤销设备。所有命令使用 .venv Python。
- YouTube 公司 OAuth 下载入口不再依赖自动化开关。公司配置尚未部署时显示具体错误，不指挥客户自行建立 Cloud 项目；令牌仍留本机。
- 无人值守仍仅开放已通过实测的 YouTube 灰度账户，浏览器平台待独立验收；不得让本机预授权绕过服务端开关、规则版本或预算。
- Mac 开机、用户已登录、网络和本机授权有效是执行前提。与 maintenance/monitoring 分开安装；旧任务需卸载后经确认重装，不由更新源码偷偷更改。

macOS uses a GUI-session LaunchAgent and Keychain-backed markers; Windows uses the existing interactive-user task and DPAPI. Real Mac, account authorization, publication and recovery acceptance remain pending. Monitoring is independent, read-only, every 15 minutes with hourly full local checks. Company YouTube configuration delivery does not require enabling unattended execution. Platform rollout remains gated by real acceptance.


## v3.1.1 报价握手 / Pricing handshake

受控执行先核实余额接口声明 quote_mode_supported=true，再通过只读 get_balance.quote_request 查询每镜报价。没有能力声明时，doctor标为待处理；不得通过生成工具试探报价。将每镜报价写入持久化步骤后才用同一请求号和max_credits创建，网络重试不改预算。报价不会建任务、冻结积分或迁移参考素材。旧API或滚动发布节点漏掉报价时停止；不能把余额当报价。

Preview only through get_balance with quote_request={tool,arguments}. Check the capability and explicit generation_quote no-task/no-reservation response. Persist each cap before creating and keep it during retries. A price above the cap is rejected before freezing. Deployment and new tool discovery are required; do not test unknown quote flags on paid tools.


首次安装 Chromium 的实测下载量约 330 MB，实际大小随版本与平台变化。
A clean installation downloaded about 330 MB for Chromium in testing.

### YouTube 一次启用 / YouTube setup

仅在客户明确要求同时启用 YouTube 自动发布时，运行 python toolkit.py enable-youtube。完成授权后，以返回的 tasks 在客户机 AI 助理的原生定时功能分别登记制作和发布，使用返回的时区及本机命令。按 phase 更新已有任务，避免重复。若 AI 助理不支持定时或本机执行，报告该限制。用 python toolkit.py assistant-schedule 重新读取授权时间。此流程由 AI 助理调度。
Run python toolkit.py enable-youtube only when the customer requests automatic YouTube publishing. Register or update the returned production and publication tasks in the customer AI assistant's native scheduler. Use the returned timezone and local commands. If the assistant cannot schedule local execution, report that limitation. Use python toolkit.py assistant-schedule to retrieve the schedule again.

只启用自动创作时运行 python toolkit.py enable-production，按返回配置登记制作任务。成片留待审核。
For production only, run python toolkit.py enable-production and register the returned production task. Films stay in review.
