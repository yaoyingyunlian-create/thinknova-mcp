# 客户 AI 助理调度与发布交接 / Assistant scheduling and publishing handoff

1. 工具包只制作。普通 MCP 生成复用 OAuth；run-day / 单次脚本执行复用已有 ThinkNova 制作预算及设备执行凭据，不需要 YouTube 频道授权。
2. 客户 AI 助理的原生定时功能复用现有 MCP 连接。按当天项目和客户确认的预算报价、生成、取件，保留原请求号，再调用工具包拼片与质检。无需试点申请或设备配对。
3. `toolkit.py assistant-schedule` 只返回流程建议，不注册任何电脑任务。客户 AI 助理自行登记，按项目去重。
4. 客户 AI 助理使用 Ego Lite 处理对应社交账号的登录、发布和结果核验。它按客户已确认的作品与授权操作；未知结果先核对，单个平台失败不阻塞其他平台。
5. 旧 tick / tick-produce / tick-publish、安装器和 YouTube 启用入口已退休，调用不再生成或上传。旧 AI 任务需更新到单次制作入口；旧 ThinkNova 系统任务只提供显式清理，不删除客户数据。

The toolkit makes videos; the customer's AI assistant owns timing and publication. Use its native timer with the existing MCP OAuth connection for quotes and generation, then use the toolkit for assembly and checks. No trial enrollment or pairing is needed. assistant-schedule only returns production suggestions. Ego Lite handles platform account checks and authorized posting. Retired toolkit timers and publishers do nothing. Existing production grants, budgets and task IDs are preserved; no Google OAuth or OS task is required to make a video.
