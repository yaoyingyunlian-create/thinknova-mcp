## 原生对白制作 / Native dialogue production

新版门店制作默认 native_dialogue_v1，保留视频模型原声，字幕后加；不默认另做TTS或为了字速改变原音速度。语速快慢及自然停顿记警告。只在不损伤口播、不使片长越界时裁段间首尾空白。已有台词可补字幕；缺字幕内容保留待审预览并指出缺项，不要求重生成。损坏、黑屏、整片无声、严重对白错配及错误规格仍阻断，发布继续沿用当前授权和首片审核。回查实际成片与哈希质检凭据，不以单一 READY.json 文件是否存在判断交付。
New store films use native_dialogue_v1 and preserve model-generated dialogue. Use only the original ThinkNova audio. Do not use local TTS, macOS say, muting, or replacement audio. Pace and natural pauses warn. Trim boundary blanks only within the film-duration allowance. Reuse existing approved dialogue for captions; missing caption content keeps a preview pending with a concrete issue, never a request to regenerate by default. Unusable media and severe mismatch still block. Existing publication consent and first-film review remain. Find delivery artifacts and hash-bound receipts rather than relying on one READY.json filename.

---
name: spoken-script
description: 写短视频对白时用。让台词像真人随口说，不像念稿。
---

> 新版日计划（schema_version=3）先读 `rules/store-film-rules-v3.md`。对白必须在画内，由顾客和店员交替说。
> For v3 plans, use the in-scene dialogue rules in `rules/store-film-rules-v3.md`. Use a question and its answer in every segment.

# 口语台词

每段至少一问一答。人物只讲自己的事，不给对方播报动作，也不预告下一步。避免采访式的服务清单，预约由店员自然带出。

## 写法

- 修订60每段5～8句、一句3～12字、一人连说不超过两句；段2承接段1；旧计划按原句数。字数按账号规则与当前片型校验，账号未写时默认 55～62 字（不计标点）。两人各说自己的事，问句由另一人接话回答。
- 避免介绍服务清单、描述眼前动作及预告下一步。把可见的动作写在对白外。
- 预约方式由店员用一句口语交代。已核实资料中的价格、活动和具体数字可以讲，按资料原话和适用日期使用。
- 每段对照 `rules/store-film-rules-v3.md` 的默认规则，账号自查已写明时逐条用账号自查并附证据。核对本片与过去七天台词，交付时逐字对照字幕。

## English summary

Write a conversation, with a real question and an answer in each segment. Use three or four lines and the account’s dialogue budget, falling back to 55–62 Chinese characters. Keep stage directions outside the spoken lines. Use confirmed facts and keep booking instructions brief.

修订60：每段5～8句、总55～62字，短接话仍计对白与字幕，只免计情境句额度；第二段接第一段末句，第二卖点由对方问出，至少两处自然反应。门店结尾说已确认地址，缺地址不编造或停工。
Revision 60: use 5–8 connected lines and 55–62 Chinese characters per segment. Short reactions remain in dialogue, captions and total counts; only the context quota is exempt. Bridge segments, let the other person elicit the second benefit, and include two natural reactions. Speak a confirmed address in store-film endings; never invent a missing address or block production for it.
