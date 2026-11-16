---
name: store-film
description: 片段都生成好之后，拼成片、验收、交给店主之前必须先读。管三件事：怎么拼、怎么验、交付时给什么。做什么片看「每日出片规范」，提示词怎么写看「镜头提示词」。
---

# 门店成片（拼、验、交）

> 11-12 版，替换 11-10 版。删掉了旧版的六拍结构、一段 15 秒剪三镜、脸不进画面（这些现在由「每日出片规范」和「镜头提示词」管，只留一处说）。
> 做到这份文件的标准才算交付了一条片。只生成几段视频、没拼成片、没过验收，都不算完成。

## 〇、分工
- 画面、视频、声音：只调 ThinkNova 的工具生成。
- 拼片、字幕、检查、发布：只跑工具包脚本（render/assemble.py、render/check.py、publish/dispatch.py），一件事一条命令。
- 你只做三件事：读店铺档案和规矩本、照技能填提示词和 job.json、调工具和脚本，把结果给店主看。
- ⛔ 用你自己的生图、生视频、网页动画、幻灯片模板给客户做内容；⛔ 为了做片去读工具包源码；⛔ 因为没有预算就换不花积分的办法代替。

## 一、先报价
get_balance 的 quote_request 把这条片要的首帧和每段视频逐项报出来（视频带 `duration_seconds`），合计一句话告诉店主。在店主给过的每日上限内直接做；超了才问。网络重试沿用原请求号。

## 二、怎么拼
现有日计划由工具包生成拼片配置。手工准备画内对白片时，产品填一段，15 秒服务片填两段；服务片用 `dialogue_segment_count: 2` 和 `short_dialogue_seconds: 30`，单段用该段的报价时长。用 `closing_overlay` 把确认过的信息叠在最后 2.5 秒，画内对白片不填写 `end_card`。旧的六拍模板仅适用于旧计划。
```
.venv/bin/python render/assemble.py job.json --json
```
- **整段用，段与段直接接。** 台词写够了的片段不用裁。只裁两种：每段开头结尾多出来的空白（超过 1 秒才裁，量法：`ffmpeg -i clip.mp4 -af silencedetect=noise=-35dB:d=0.4 -f null -`）；某个阶段画面坏了（多了字、人走样），只剪掉那一阶段。
- 片段里有超过 1 秒的没人声：不是去剪画面，是台词写短了——下次把这一段台词写够；这一次用配乐垫住，或把这一段带着更长的台词重新生成（先说明费用）。
- `subs` 逐字照台词写，每屏一句、不超过 8 个非空白字符（字号 90）；长句拆成几屏。双语在旁边加 `subs2`，条数一一对应。
- 店名或主推项必须在口播或字幕里出现至少一次（不靠片尾卡）。片尾卡按平台：小红书版不加片尾卡；其他平台 2～3 秒，店名 + 一句这家店解决什么。联系方式和地址放账号主页资料，不放进片子。
- 有店主批准的配乐就加 `music`，`music_db` 用 -22。

## 三、验收：全部通过才交付
`.venv/bin/python render/check.py 成片.mp4 --film --outro-start <片尾卡开始的秒数> --sheet 输出目录`，再打开联系表逐项看：
- [ ] 画内对白片符合计划时长（单段或两段 30 秒），竖屏 1080×1920，机器检查没有 FAIL
- [ ] 第一秒有人在做事，不是文字卡、不是空镜
- [ ] 画内对白片检查至片尾叠字前，口播空档不超过 2 秒；允许自然的换人停顿。旧计划仍用自身门槛。
- [ ] 全片是同一个人：脸、发型、衣服没变；店里的镜头看得出是这家店
- [ ] 对照脚本回听两人的对白、发音和角色声音，确认人物、产品和动作符合档案。
- [ ] 画面里没有模型自己加的字；字幕和声音逐句对得上（`render/speech_review.py` 核店名、产品名）
- [ ] 没有编出来的价格、优惠、评价、效果

⛔ 自己给自己判通过：机器检查有 FAIL 就改；WARN 原样告诉店主，不改写成「不是问题」。
有一项不过：先用已有片段重新剪（不花钱）；要重新生成就先说明费用。

## 四、交付时给什么
成片、逐段对白原文、实际生效的参考图及质检原文交给审核人。旧任务无法回读实际参考图时标为未知。另附各平台发布清单。清单每个平台一行：标题、正文、标签、发布时间。只列店主选了的平台。

**标题、正文、标签每个平台单独写**，⛔ 一份文案复制到所有平台。先读 get_content_rules 的 platform_rules，有硬性规定按规定，没有的按下表：

| 平台 | 标题 | 正文 | 标签 |
|---|---|---|---|
| 小红书 | ≤20 字，重点放前 7 个字 | 3～5 行，像顾客在分享；⛔ 链接、电话、「私信」 | 2 个（行业词 + 地区词） |
| TikTok | 封面字 1 句（英文 ≤6 个词） | 1～2 句口语 | 3～5 个，含地区 |
| Instagram | 第一行就是钩子 | 2～4 行 | 5～8 个，大小搭配 |
| Facebook | 第一行说清是什么店 | 2～4 行 | 0～3 个 |
| YouTube Shorts | ≤60 字符，直说是什么店的什么事 | 1～2 行 | 3 个，写在正文末尾 |
| X | — | ≤200 字符一句话 | 1～2 个 |

写法：标题是这条片讲的那件具体的事加地点词；正文第一行重复开场那句，第二行一个具体信息，活动周加起止日期。AI 标注只打开平台自带的开关，⛔ 在正文里再写免责声明。

普通发布按本条作品确认。经明确授权并已验收的无人值守发布按已授权的账号、预算和排期执行。 Ordinary publishing requires approval for the current work. Validated unattended publishing follows the confirmed authorization.

## English summary
For in-scene dialogue, use one planned shot or two 15-second service segments. Overlay confirmed closing text on the last 2.5 seconds of the footage. At size 90 split Chinese captions to at most eight characters per screen, keeping translations aligned with the primary cues. Review the contact sheet and listen against the script for action, identities and spoken lines. The review package includes the film, each segment’s dialogue, the references confirmed by the generation receipt, and the original machine check report. Legacy plans continue to use their own timing profile.
