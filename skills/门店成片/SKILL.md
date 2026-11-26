## 原生对白制作 / Native dialogue production

新版门店制作默认 native_dialogue_v1，保留视频模型原声，字幕后加；不默认另做TTS或为了字速改变原音速度。语速快慢及自然停顿记警告。只在不损伤口播、不使片长越界时裁段间首尾空白。已有台词可补字幕；缺字幕内容保留待审预览并指出缺项，不要求重生成。损坏、黑屏、整片无声、严重对白错配及错误规格仍阻断，发布继续沿用当前授权和首片审核。回查实际成片与哈希质检凭据，不以单一 READY.json 文件是否存在判断交付。
New store films use native_dialogue_v1 and preserve model-generated dialogue. Use only the original ThinkNova audio. Do not use local TTS, macOS say, muting, or replacement audio. Pace and natural pauses warn. Trim boundary blanks only within the film-duration allowance. Reuse existing approved dialogue for captions; missing caption content keeps a preview pending with a concrete issue, never a request to regenerate by default. Unusable media and severe mismatch still block. Existing publication consent and first-film review remain. Find delivery artifacts and hash-bound receipts rather than relying on one READY.json filename.

---
name: store-film
description: 片段都生成好之后，拼成片、验收、交给店主之前必须先读。管三件事：怎么拼、怎么验、交付时给什么。做什么片看「每日出片规范」，提示词怎么写看「镜头提示词」。
---

# 门店成片（拼、验、交）

> 11-12 版，替换 11-10 版。删掉了旧版的六拍结构、一段 15 秒剪三镜、脸不进画面（这些现在由「每日出片规范」和「镜头提示词」管，只留一处说）。
> 做到这份文件的标准才算交付了一条片。只生成几段视频、没拼成片、没过验收，都不算完成。

## 〇、分工
- 画面、视频、声音：只调 ThinkNova 的工具生成。
拼片、字幕和质检使用工具包；逐平台待审清单只在本机准备。实际发布使用客户AI助理的原生定时任务与Ego Lite，遵守客户已确认的账号、作品和授权。
- 你只做三件事：读店铺档案和规矩本、照技能填提示词和 job.json、调工具和脚本，把结果给店主看。
- ⛔ 用你自己的生图、生视频、网页动画、幻灯片模板给客户做内容；⛔ 为了做片去读工具包源码；⛔ 因为没有预算就换不花积分的办法代替。

## 一、先报价
get_balance 的 quote_request 把这条片要的首帧和每段视频逐项报出来（视频带 `duration_seconds`），合计一句话告诉店主。在店主给过的每日上限内直接做；超了才问。网络重试沿用原请求号。

从 MCP 读取当前修订的创作规则。规则附有餐饮、美业和商品的逐句画面范例时，只借用结构，使用客户自己的已确认事实和素材。逐句稿单独提交为 `dialogue`。门店报价返回 `quote_fingerprint` 时，建单沿用该值及原参数。收到 `MCP_STORE_QUOTE_CHANGED` 时先重新报价。

Read the effective creation rules from MCP. Use the food, beauty and retail dialogue examples as structure for the customer's own verified facts. Submit speaker and text in `dialogue`. When the quote includes `quote_fingerprint`, carry it with the unchanged generation arguments. Request a fresh quote if ThinkNova returns `MCP_STORE_QUOTE_CHANGED`.

## 二、怎么拼

按生效报价规划约三段 10–15 秒的场景，段间硬切。手写多场景 job 用 `film_profile: "store_v2"`、`film_schema_version: 3`、`film_type: "explainer"`、`story_narrative: true`，登记实际片段数和源素材时长，各段用 `planned_seconds`。用 `closing_overlay` 在正常画面上叠店名和一个已核实的行动。逐句字幕随原生对白对齐，渲染最后把画面和声音同步加速到 1.25 倍、保留原音高，字幕同轴缩放。最终尽量 30–40 秒，最长 60 秒。

Use roughly three 10–15 second scenes with hard cuts. Align captions to the generated dialogue before the toolkit applies 1.25x final playback with pitch-preserving audio. Aim for 30–40 seconds after playback scaling and cap delivery at 60 seconds.

For revision 2.4, ordinary product and service films use two 15-second segments. Use a closing overlay unless the customer explicitly asks for a separate card. Explainer films use 3–4 segments, each 10–15 seconds, totaling 45–60 seconds. Reuse the original dialogue track across cutaways.

日计划由工具包生成拼片配置。手工讲解种草填 `film_type: "explainer"`、各段 `dur`、实际段数和合计时长。独立片尾卡仅按客户明确要求使用，此时用 `end_card`。旧的六拍模板用于旧计划。
```
.venv/bin/python render/assemble.py job.json --json
```
- **整段用，段与段直接接。** 台词写够了的片段不用裁。只裁两种：每段开头结尾多出来的空白（超过 1 秒才裁，量法：`ffmpeg -i clip.mp4 -af silencedetect=noise=-35dB:d=0.4 -f null -`）；某个阶段画面坏了（多了字、人走样），只剪掉那一阶段。
- 片段里出现意外空档时，回听原声并记录时间段。先用原片缩短可剪空档，保留完整对白和自然换气，再重新对齐字幕。
- `subs` 逐字照台词写，每屏一句、不超过 8 个非空白字符（字号 90）；长句拆成几屏。双语在旁边加 `subs2`，条数一一对应。
- 门店片两种语言均使用白字黑描边。Store captions use white text with a black outline in both languages.
- 口播或字幕必须含店名或主推项。到店片由店里的人说一个已核实的位置提示或预约动作，并将店名和该项信息叠在原画面末尾。完整地址和电话放账号主页。
- 有店主批准的配乐就加 `music`，`music_db` 用 -22。

## 三、验收：全部通过才交付
使用拼片输出的质检报告与联系表。拼片会把实际片尾起点和计划时长传给质检器：
- [ ] 画内对白片符合当前计划时长，竖屏 1080×1920，机器检查通过
- [ ] 第一秒有人在做事，不是文字卡、不是空镜
- [ ] 画内对白片检查至片尾叠字前，口播空档不超过 2 秒；允许自然的换人停顿。旧计划仍用自身门槛。
- [ ] 全片是同一个人：脸、发型、衣服没变；店里的镜头看得出是这家店
- [ ] 对照脚本回听两人的对白、发音和角色声音，确认人物、产品和动作符合档案。
- [ ] 画面里没有模型自己加的字；字幕和声音逐句对得上（`render/speech_review.py` 核店名、产品名）
- [ ] 没有编出来的价格、优惠、评价、效果

⛔ 自己给自己判通过：按服务器质量政策处理：真正不可用的 FAIL 修复；WARN 记录并随成片交付，不增加确认步骤。WARN 原样告诉店主，不改写成「不是问题」。
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
For ordinary in-scene dialogue, use two 15-second segments. Overlay confirmed closing text on the last 2.5 seconds by default. At size 90 split Chinese captions to at most eight characters per screen, keeping translations aligned. Review the contact sheet and listen against the script. Include the film, dialogue, applied references and the machine report. Resume legacy plans with their original timing profile.


修订64执行补充：按 rules/store-film-rules-v64.md 开工。先确认主推项、三条不同的卖点和一个收尾动作；缺资料先问并保存已确认规则。缺照片或顾客原话按规则使用示意素材或店员说明。脚本独立盲审，每段 4～6 句，逐句字幕保留原文标点。旧任务按原契约续跑。
Revision 60 uses the current server rules and prepares missing illustrative assets automatically within the approved budget. Missing shop names or quotes do not block a film. Apply server policy 58 warnings and bounded speech recovery where enabled; unknown ASR is explicitly recorded and does not create another approval requirement within a valid publication grant. Old plans keep their original contracts.

修订60：每段5～8句、总55～62字，短接话仍计对白与字幕，只免计情境句额度；第二段接第一段末句，第二卖点由对方问出，至少两处自然反应。门店结尾说已确认地址，缺地址不编造或停工。
Revision 60: use 5–8 connected lines and 55–62 Chinese characters per segment. Short reactions remain in dialogue, captions and total counts; only the context quota is exempt. Bridge segments, let the other person elicit the second benefit, and include two natural reactions. Speak a confirmed address in store-film endings; never invent a missing address or block production for it.

修订 65（以 MCP 返回的生效修订为准）：主推项、三条不同已确认卖点、一个行动指引，缺一就只问缺项，保存确认后的项目规则再报价。多段固定同一获授权人物板，用 edit_image 备竖屏首帧再 animate_image。4–8 句覆盖生效时长的 80%–93.33%，对白只用原生音轨，字幕源自逐句稿。店员可对镜头说咨询动作。段内与段间长空档先从原素材剪，保留可靠对白和动作。已有任务复用原任务号。

Revision 65 applies when active on MCP. Ask only for missing facts before quoting: featured item, three distinct verified facts, and one viewer action. Use a shared approved continuity board, portrait first frames, and native dialogue only. Write 4–8 lines filling 80%–93.33% of the effective duration. Trim verified unwanted gaps and re-time exact-script captions. Resume existing tasks as recorded.
