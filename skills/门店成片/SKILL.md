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
复制 `render/templates/门店成片_6拍.json` 另存，按片段顺序填：
```
.venv/bin/python render/assemble.py job.json --json
```
- **整段用，段与段直接接。** 台词写够了的片段不用裁。只裁两种：每段开头结尾多出来的空白（超过 1 秒才裁，量法：`ffmpeg -i clip.mp4 -af silencedetect=noise=-35dB:d=0.4 -f null -`）；某个阶段画面坏了（多了字、人走样），只剪掉那一阶段。
- 片段里有超过 1 秒的没人声：不是去剪画面，是台词写短了——下次把这一段台词写够；这一次用配乐垫住，或把这一段带着更长的台词重新生成（先说明费用）。
- `subs` 逐字照台词写，每屏一句、不超过 9 个字（字号 90）；长句拆成几屏。双语在旁边加 `subs2`，条数一一对应。
- 店名或主推项必须在口播或字幕里出现至少一次（不靠片尾卡）。片尾卡按平台：小红书版不加片尾卡；其他平台 2～3 秒，店名 + 一句这家店解决什么。联系方式和地址放账号主页资料，不放进片子。
- 有店主批准的配乐就加 `music`，`music_db` 用 -22。

## 三、验收：全部通过才交付
`.venv/bin/python render/check.py 成片.mp4 --film --outro-start <片尾卡开始的秒数> --sheet 输出目录`，再打开联系表逐项看：
- [ ] 30～40 秒，1080×1920，机器检查没有 FAIL
- [ ] 第一秒有人在做事，不是文字卡、不是空镜
- [ ] 除片尾卡外，连续没人声不超过 1 秒
- [ ] 全片是同一个人：脸、发型、衣服没变；店里的镜头看得出是这家店
- [ ] 全片旁白是同一个性别、听得出是同一个人（小的音色差别放过）
- [ ] 画面里没有模型自己加的字；字幕和声音逐句对得上（`render/speech_review.py` 核店名、产品名）
- [ ] 没有编出来的价格、优惠、评价、效果

⛔ 自己给自己判通过：机器检查有 FAIL 就改；WARN 原样告诉店主，不改写成「不是问题」。
有一项不过：先用已有片段重新剪（不花钱）；要重新生成就先说明费用。

## 四、交付时给什么
成片 + 各平台发布清单。清单每个平台一行：标题、正文、标签、发布时间。只列店主选了的平台。

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

店主确认这一条后才发布。

## English summary
After clips are generated: quote every item first (with duration_seconds) and stay within the owner's daily cap. Assemble with render/assemble.py from the store-film template, trimming each clip to the spoken lines (0.3 s before the first word, 0.3 s after the last) and cutting out only the bad phase of a clip. Captions copy the spoken lines verbatim, max 9 characters per screen at size 90. End card: shop name plus what the shop solves; contact details live in the profile bio. Pass check.py --film plus the manual checklist (action in the first second, no speech gap over 1 s, same person and same shop throughout, one narrator, no model-drawn text, no invented claims); never self-approve past a FAIL or reword a WARN. Deliver the film with per-platform copy written separately; AI disclosure via the platform toggle only.


## 当前脚本入口

新版门店任务使用 film_profile=store_v2，并填写 film_type、shop_name、featured_service。剧情片在 clips 中标注 pain、process、change、service 四拍，生成按场景分段。双语按句填写 subs 和 subs2，两个列表逐屏对应。报价与建单均带 duration_seconds；resolution 以实际报价为准；真实门店或产品使用 visual_subject=customer_identity。质检失败时向客户交付诊断，技术人员可以从本机待审记录复检。店主确认最终成片和发布清单后方可发布。

For store_v2, declare the four story beats, keep bilingual sentence pairs aligned, use confirmed portrait first frames and check supported video options in the quote. Failed checks produce diagnostics for the customer. A passing film and the owner's approval are required before publishing.