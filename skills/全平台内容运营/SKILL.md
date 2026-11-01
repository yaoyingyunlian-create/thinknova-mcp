---
name: thinknova-cross-platform-workflow
description: 加载 ThinkNova 自动化工具包后，用于从用户目标到本地渲染、质检、演练和经确认发布的跨平台工作流。
---

# ThinkNova 全平台内容运营

会员首次连接后自动按 get_toolkit 的 HTTPS 指引初始化工具包；缺项自动修复，不再询问下载。已有安装发现新版时才询问是否更新；不要覆盖客户记忆或登录态。

先用简短访谈收集已缺失的信息：目标（获客、品牌曝光、互动、引流或转化）、受众、目标平台、风格/语言/禁忌、可用且已授权的素材、审核和发布偏好。基于回答给出简短内容方案，获得同意后才生成。

只能选择工具包实际支持的平台：YouTube、TikTok、小红书、抖音、Facebook（主页 Reels）、Instagram（Reels 或轮播）、LinkedIn（纯文字）和 X（文字加视频/图片）。按 `job.example.json` 为平台填写覆盖字段；不要虚构其他平台能力。

详细执行以工具包 AGENTS.md 为准。读取 get_content_rules，按 needs_onboarding 主动补问并保存；网络重试复用请求号，终态失败重做按已授权预算处理，不承诺免费重抽。

本机执行制作和发布。YouTube --dry 仅本地检查，--execute 才真实上传；其他平台演练可能上传素材或留下草稿。真实上传/发布、改定时和再次发布都取得对应版本、平台账号、时间的当次明确确认。凭据由用户本人处理，不上传记忆或登录态。定时维护只采集、归档和写本地提醒，不能承诺自动唤醒 AI。

English: first member setup is automatic; updates require approval. Follow AGENTS.md for rule interviews, paid retry handling and approval records. YouTube --dry is local only; other dry-runs may upload assets. Confirm each real upload/publication and keep credentials local. Maintenance never starts an AI session.
