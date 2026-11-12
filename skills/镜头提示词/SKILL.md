---
name: shot-prompts
description: 写任何一条首帧（generate_image / edit_image）或图生视频（animate_image）提示词之前必须先读。给出固定要加的话、参考图怎么放、人物怎么锁、台词和声音怎么写、不能写的画面和失败怎么办。
---

# 镜头提示词（每写一条提示词都要套）

> 这份管「一条提示词怎么写」；「每日出片规范」管「做什么片、一条片必须做到什么」；「门店成片」管「怎么拼、怎么验、怎么交」。
> 11-12 版，替换 11-10 版。改动：人物一律是 AI 虚构角色、可以露脸、用三视图；按场景分段生成，秒数按台词定；声音设定分两句。

## 〇、提示词本身的四条纪律（先于一切）
1. **短。** 平台上限是 4000 字节（不是字数，一个汉字 3 字节），而且账号里存的店铺规则会自动加在最前面一起算。你写的这一段控制在 1200 字节以内；提交前数一遍总长，超过 3500 字节就删，⛔ 指望平台帮你截（它从尾巴截，最后几句最重要的话会被悄悄砍掉）。
2. **要紧的放前面。** 顺序固定：延续首帧那句 → 这一段做什么 → 台词 → 声音 → 不出字不出音乐。⛔ 把「不要出字」只写在最后。
3. **一件事只说一遍。** 同一个要求换三种说法重复写，不会更听话，只会挤掉别的内容。
4. **写要它做什么，少写不许做什么。** 禁止的话只留固定的那两行，⛔ 列一长串「不要 A、不要 B、不要 C」。
另：存进账号的内容规则（save_content_rules）只放和画面有关的三句（主角是谁、画面风格、画面不出字），越短越好；流程、字幕、发布、审核类规矩写在本地文件里，⛔ 存进账号规则。

## 一、固定要加的话（一个字不改）

**首帧结尾加：**
```
Photorealistic documentary photo, 9:16 vertical, natural light, real shop atmosphere.
No readable text anywhere: signs, labels, paper and phone screens are blurred or face away. No logos, no watermarks.
```
有客户的产品时再加：`The product packaging keeps exactly the same shape, colour, logo and printed text as the reference photo.`

**图生视频开头加：**
```
Continue exactly from this frame. Keep the same person, clothes, shop and product as in the frame.
```
**图生视频结尾加：**
```
No subtitles, no captions, no on-screen text, no logos, no background music.
Natural hands with five fingers. Slow, steady camera.
```

## 二、参考图怎么放（每镜首帧最多 3 张，顺序不能错）
1. 这一镜发生在店里 → 第 1 张放这个位置的门店真实照片。不在店里不放。
2. 有主角 → 放三视图设定板。
3. 有产品 → 放产品真实照片。
图生视频的第 1 张必须是这一镜的首帧。提交后用 get_task 回读，确认存进去的顺序没错。同一个位置的几镜用同一张门店照片；连续动作的下一镜，首帧用上一镜视频的最后一帧。
带了门店或产品真实照片的调用传 `visual_subject=customer_identity`。

## 三、人物锁定
片里的人一律是 AI 生成的虚构角色，可以露脸。只有店主给了本人照片并同意，才用真人。
1. **三视图设定板**：同一个人的正面、侧面、背面全身，同一身衣服，白底，1:1，一张图排三栏。每个角色只出一张，出完就用它，⛔ 重复出，⛔ 只出一张半身照。
2. **一段固定外貌描述**（年龄段、发型发色、上衣、下装、配饰），每条提示词原样复制，⛔ 换说法（「一位顾客」「一位女士」会被当成不同的人）。
3. 每镜首帧都带设定板当参考（位置见第二节）。
4. 生成后逐镜看：脸、衣服、发型、手不一样的镜头不用。

## 四、台词和声音

中文台词先按秒数 × 4 估算，低于秒数 × 3.8 检查是否留了过多空档。声音描述保持固定音色，并使用自然偏快的口语节奏（brisk conversational pace）。成片会按实际转写复测语速。 Draft about four Chinese characters per second, with a brisk conversational pace.
> 工具包有配音工具之前，声音由视频模型按提示词直接说。有了以后改成画面不说话、旁白另配。
1. 台词写进图生视频提示词，放在「」里。**按场景分段**：同一个地方的连续动作写成一段，里面分 2～3 个阶段，每阶段一句台词；换地方才开新的一段。台词要写够这一段说：6 秒 20～24 字，10 秒 35～40 字，15 秒 50～55 字；报价和建单都带 `duration_seconds`。出来整段用，不靠后期裁。⛔ 不带时长（默认出 15 秒）；⛔ 一个镜头生成一次。
2. 台词是主角自己在说，用「我」，像在跟朋友讲；一句里留一个停顿。写法照「口语台词」。
3. 声音设定两句：
   - 第一句固定身份，全片一字不改，写明性别、音高、音色，例：`Voice: the same woman in every shot — clearly feminine, light and clear, medium-high pitch, about 30, natural Mandarin, first-person voice-over, no lip-sync.`
   - 第二句是这一镜的情绪，每镜不同，例：`Tone in this shot: tired, a little irritable.`
4. 出片后逐镜听：性别不对或明显换了人，在第一句后面加强描述重做一次（原样重做没用）；小的音色差别放过。
5. 价格和带单位的数字不念，放字幕和文案。多音字、难读的词换掉；品牌名要念就注明读法，不确定就不念。
6. 方言要写明（如 `Cantonese, NOT Mandarin`），台词用方言字写。

## 五、一条完整的图生视频提示词
```
Continue exactly from this frame. Keep the same person, clothes, shop and product as in the frame.
Person: <固定外貌描述，原样复制>.
0-5 s: <动作 + 景别 + 运镜>. Voice-over: 「<台词>」
5-10 s: <换一个景别或动作>. Voice-over: 「<台词>」
10-14 s: <再换>. Voice-over: 「<台词>」
Voice: <固定身份句，原样复制>
Tone: <这一段里情绪怎么走，例：starts tired, ends a little curious>.
Ambient sound of the place, low.
No subtitles, no captions, no on-screen text, no logos, no background music.
Natural hands with five fingers. Slow, steady camera.
```

## 六、不能写的画面
| 不能写 | 会出什么问题 | 改成 |
|---|---|---|
| 让模型画字幕、标题、价格、包装上的字 | 乱码字，后期再加字幕就两层 | 结尾固定写 no text；字由 render/assemble.py 加 |
| 背景音乐 | 和台词抢，拼片时断断续续 | 写 no background music；配乐拼片时统一加 |
| 让模型凭空画门面、招牌、菜单板 | 冒出街景和乱码字，也不是客户的店 | 用门店真实照片当第 1 张参考 |
| 日历、手写字、手机或电脑屏幕正面 | 乱码数字、假界面 | 屏幕背对或虚化 |
| 一镜里混两种风格（3D 示意 + 实拍） | 画面跳 | 一镜一种风格 |
| 店里的镜头不带门店照片，只凭文字生成 | 每镜的店都不一样 | 照第二节放参考图 |
| generate_video 凭文字直接出片 | 人、店、货每镜都不一样 | 先出首帧，再 animate_image |

## 七、失败和重提
- 返回 `Provider task failed` / `Internal Error`：原样重提一次；第二次还失败就停下告诉店主。
- 同时提交多条时每条隔 2 秒；有一条没返回任务号，先 get_task 查有没有建成，没有再单独重提。
- 下载失败先重试下载，⛔ 为了下载失败去重新生成。
- 画面里有模型自己加的字：提示词不改重提一次（先报价）；第二次还有就停下告诉店主。

## 八、提交前自查
- [ ] 店里的镜头：门店照片是第 1 张参考；有主角带了三视图；有产品带了产品照片
- [ ] 首帧结尾加了固定段；视频开头是 `Continue exactly from this frame`，结尾写了不出字、不出音乐
- [ ] 台词用「我」，字数在上限内；带了 `duration_seconds`，报价也带了
- [ ] 外貌描述、声音固定句和前面几镜一字不差；这一镜写了自己的情绪句
- [ ] 台词里没有价格、带单位的数字、多音字

## English summary
Before any first-frame or animate_image prompt: append the fixed tails (photorealistic 9:16, no readable text; "Continue exactly from this frame…"; no subtitles, text or music). Order references: the real shop photo for that location first when the shot is in the shop, then the three-view character sheet, then the real product photo; pass visual_subject=customer_identity when real shop or product photos are used; verify stored order with get_task. Characters are AI-generated fictional people who may show their face, locked by one three-view sheet and one appearance paragraph copied verbatim. Write the spoken line first, then set duration_seconds = characters ÷ 4 + 1 (6–15) and pass it in both quote and creation. Lines are first person, conversational, with room to breathe. Voice is two sentences: a fixed identity sentence repeated verbatim and a per-shot tone sentence. No prices or unit numbers in speech. Never text-only video generation; never let the model draw text, signage or music.
