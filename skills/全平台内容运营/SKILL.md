---
name: thinknova-cross-platform-workflow
description: 加载 ThinkNova 自动化工具包后，用于从用户目标到本地渲染、质检、演练和经确认发布的跨平台工作流。
---

# ThinkNova 全平台内容运营

会员首次连接后自动按 get_toolkit 的 HTTPS 指引初始化工具包；缺项自动修复，不再询问下载。已有安装发现新版时自动按官方恢复流程更新；不要覆盖客户记忆或登录态。

修订60只在不知道产品或服务时提问。复用已知信息和默认值；没有店名、照片、顾客原话或详细卖点不等待补齐。按已批准预算自动准备素材、出片及文案，缺项随片列清单。首片审核和发布继续遵守现有授权。

只能选择工具包实际支持的平台：YouTube、TikTok、小红书、抖音、Facebook（主页 Reels）、Instagram（Reels 或轮播）、LinkedIn（纯文字）和 X（文字加视频/图片）。按 `job.example.json` 为平台填写覆盖字段；不要虚构其他平台能力。

先读取服务器平台规则，区分硬性约束与运营建议。各平台独立写标题、正文和标签；比较近七天内容并记录变化原因。拼片使用 render/assemble.py，普通发布使用 publish/dispatch.py，禁止自行另写绕过授权的发布/渲染程序。所有 --dry 仅本地检查，不上传；可以在明确授权后直接完成首条真实发布，无须上传演练。

详细执行以工具包 AGENTS.md 为准。读取 get_content_rules，使用 effective_rules，不重复六字段访谈；网络重试复用请求号，终态失败重做按已授权预算处理，不承诺免费重抽。

本机执行制作和发布。YouTube --dry 仅本地检查，--execute 才真实上传；所有平台 --dry 都是本地检查，不上传或创建草稿。真实上传/发布、改定时和再次发布都取得对应版本、平台账号、时间的当次明确确认。凭据由用户本人处理，不上传记忆或登录态。定时维护只采集、归档和写本地提醒，不能承诺自动唤醒 AI。

English: first member setup is automatic; updates are automatic with customer files preserved. Follow AGENTS.md for rule interviews, paid retry handling and approval records. YouTube --dry is local only; all --dry modes are local-only and do not upload or create drafts. Confirm each real upload/publication and keep credentials local. Maintenance never starts an AI session.

Revision 60 continues from a known product/service and approved budget without a shop name or photos. Automatically prepare illustrative first frames, never fabricate facts, and attach optional missing items to the film. Existing publication consent still applies.

修订60：每段5～8句、总55～62字，短接话仍计对白与字幕，只免计情境句额度；第二段接第一段末句，第二卖点由对方问出，至少两处自然反应。门店结尾说已确认地址，缺地址不编造或停工。
Revision 60: use 5–8 connected lines and 55–62 Chinese characters per segment. Short reactions remain in dialogue, captions and total counts; only the context quota is exempt. Bridge segments, let the other person elicit the second benefit, and include two natural reactions. Speak a confirmed address in store-film endings; never invent a missing address or block production for it.
