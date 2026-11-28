---
name: daily-film-standard
description: 给客户排一周的片、做每天那一条之前必须先读。管三件事：店铺档案怎么建、这周做什么片（店主一句话 → 一周计划）、每条片必须做到什么。一条提示词怎么写看「镜头提示词」，怎么拼看「门店成片」。
---

> 写脚本前读取当前项目的 `get_content_rules.effective_rules`。先逐条照账号创作规则和自查执行；`rules/store-film-rules-v3.md` 只补账号未写的项。已保存的计划按原版本续跑。
> Read the project’s effective rules first and apply its checklist. Use the bundled rules for missing items. Resume saved plans using their original revision.

# 每日出片规范

> 目标：店主每周只说一句「这礼拜我要做什么」，你排出一周的片，每天做一条给他看。店主不说，就按角度表轮着做。
> 11-12 版。依据：Emily 两条样片的后台任务和成片实测、营销线的做法。

## 一、店铺档案（第一次连上时建一次，存 memory 和 save_content_rules）

复用已有资料填写档案；只有不知道卖什么时提问，下面项目不要求填满才出片：

1. **可以直接说的事实**（有几条用几条）：这家店解决什么问题、给什么人、主推的 1～3 样、做法上的特别之处（几味料、熬几小时、做多久）、店主自己的经历。每条标「店主已确认」。确认过的以后直接用，⛔ 每条片再问一遍。
2. **不能说的**：只记店主点名的和行业红线（疗效、保证、编的评价）。⛔ 把「待确认」写成默认禁止——未确认的不编，优先换已核实内容，不等待补齐。
3. **人物三视图**：店里的人固定使用一套授权三视图。每条片换一个虚构顾客，同一条片内用同一套顾客三视图。按「镜头提示词」核对每段实际采用的参考。
4. **到店片收尾与主页**：最后一句由店里的人说一个已核实的位置提示或预约动作，二选一。店名与这项信息进入字幕和片尾叠字。完整地址和电话放平台主页简介。
5. **角度表**：先读 rules/store-film-category-v54.md 对应品类，选有资料支撑的一项。首条只准备当天方案，资料不足三项或七天未排满也可继续。已核实价格可以讲，活动按有效日期执行。

| # | 角度 | 片型 | 填什么 |
|---|---|---|---|
| 1 | 痛点 | 剧情 | 主角来之前最烦的那件事 |
| 2 | 第一次来 | 剧情 | 主角第一次体验的全过程 |
| 3 | 产品 / 主推项 | 展示 | 这样东西是什么、怎么做出来的 |
| 4 | 误会 | 剧情 | 外行对这一行最常见的一个误会 |
| 5 | 店主故事 | 剧情 | 为什么开这家店 |
| 6 | 适合谁 | 剧情 | 哪种人最该来、来了解决什么 |
| 7 | 常见问题 | 剧情 | 顾客问得最多的一个问题 |

写脚本前按「做法和原因」「看得见的东西」「顾客常遇的小事」盘点已确认事实，分别存到 `shop_profile.confirmed_facts` 的 `methods_and_reasons`、`visible_details`、`customer_situations`。资料足够即按事实写，末尾附缺项。资料不足先换通用示意镜头；已有素材归属和费用授权仍在对应步骤校验。排片规则存 `editorial_instructions`，画面外观、风格、禁项存 `visual_constraints`。

新版档案补充 `category`（品类）、`viewer_action`（看完做什么）、`customer_quotes`（原话、来源及公开授权）和 `missing_information`。服装拍上身走动和细节；保健品展示外包装，从已核实的需求和特色讲，避免打开或倒出；美容美发从具体困扰和服务过程讲。缺项列清单，用能核实的资料继续。

## 二、九宫格选题和每日计划

起稿前写三行：具体受众和困扰、已核实的顾客价值、希望观众采取的行动。账号未写自查时，逐项检查：第一句有具体困扰或真实感受、至少两句有顾客好处、有真实顾客体验才引用、不用台词描述可见动作或罗列服务、每条事实可追溯。把脚本意图、自查证据和缺料清单一起交运营。缺顾客原话时略去效果表述，继续能做的片型。
Before drafting, record audience/problem, confirmed benefits and the intended action. Use the project's checklist. Send missing facts to operations, and omit any unsupported experience claim.


新版 59 按已知人群、场景、痛点和特色准备当天计划，记录选用角度与资料出处，逐日增加候选。相邻作品更换有资料支撑的角度和拍法。旧版七天计划按保存时的规则恢复。活动到期排除过期主题。

拍法可选顾客心里话、剧情、趣味剧情、探店、过程揭秘、前后对比、问答、产品特写、折扣和一天或一单。用 python toolkit.py validate-week 校验选题池，每天只准备一条可执行日计划。工具包负责报价、取件和拼片，异常写入运行诊断。

## 三、片型与画内对白

账号没有指定时采用内置七片型和对白写作默认值。新版普通产品和服务片两段各 15 秒，每段 5～8 句，逐句接话，默认 55～62 字。原样记录对白并同步字幕。参考图依照「镜头提示词」预检。

## 四、制作与提交

1. 报价与建单都带 `duration_seconds: 15` 和 `ratio: "9:16"`，逐段检查三张参考图实际生效。预算不足时指出差额。
2. 保留两个人在场的真实互动。第一秒有动作，台词遵循当前账号规则并通过当前片型校验。用工具包拼片及检查，把成片、逐段对白、实际参考图和检查原文送审。
3. 店铺、产品及授权事实从当前项目读取。对白中的价格、活动和数字均须有已核实的资料依据。字幕和片尾信息由工具包叠加。

## 五、标题和文案

- 标题 = 这条片讲的那件具体的事 + 地点词。⛔ 只有氛围没有信息的标题。
- 正文：第一行重复开场那句；第二行一个具体信息；活动周加起止日期。联系方式按客户规则，默认只写「主页有联系方式」。
- 各平台分别写，写法见「门店成片」第六节的表。
- AI 标注：只打开平台自带的 AI 标签开关，⛔ 在每条正文里再写一遍免责声明。

## 六、样片审核与后续发布

首条样片与各平台发布信息一起请店主确认。客户可在其AI助理中确认后续定时与Ego Lite发布范围。已有有效授权的合格成片按授权的账号、平台、预算和排期执行。普通发布仍按本条作品确认。

## English summary

Use the project's editorial rules. Reuse the approved staff turnaround, and choose a different customer for each film. For revision 64 store films, speak the confirmed shop name, address and one booking action in the ending and captions. If the address is unknown, omit it without inventing it or blocking creation. Quote all segments and verify applied references. Review the first film and platform copy with the customer. Later qualifying films follow the active unattended grant, when enabled.


修订64执行补充：按 rules/store-film-rules-v64.md 开工。先确认主推项、一条已核实的可公开事实和一个收尾动作；缺资料先问并保存已确认规则。缺照片或顾客原话按规则使用示意素材或店员说明。脚本独立盲审，每段 4～6 句，逐句字幕保留原文标点。旧任务按原契约续跑。
Revision 60 uses the current server rules and prepares missing illustrative assets automatically within the approved budget. Missing shop names or quotes do not block a film. Apply server policy 58 warnings and bounded speech recovery where enabled; unknown ASR is explicitly recorded and does not create another approval requirement within a valid publication grant. Old plans keep their original contracts.

修订60：每段5～8句、总55～62字，短接话仍计对白与字幕，只免计情境句额度；第二段接第一段末句，第二卖点由对方问出，至少两处自然反应。门店结尾说已确认地址，缺地址不编造或停工。
Revision 60: use 5–8 connected lines and 55–62 Chinese characters per segment. Short reactions remain in dialogue, captions and total counts; only the context quota is exempt. Bridge segments, let the other person elicit the second benefit, and include two natural reactions. Speak a confirmed address in store-film endings; never invent a missing address or block production for it.

修订 65（以 MCP 返回的生效修订为准）：主推项、一条已核实的可公开事实、一个行动指引，缺一就只问缺项，保存确认后的项目规则再报价。多段固定同一获授权人物板，用 edit_image 备竖屏首帧再 animate_image。4–8 句覆盖生效时长的 80%–93.33%，对白只用原生音轨，字幕源自逐句稿。店员可对镜头说咨询动作。段内与段间长空档先从原素材剪，保留可靠对白和动作。已有任务复用原任务号。

Revision 65 applies when active on MCP. Ask only for missing facts before quoting: featured item, one verifiable public fact, and one viewer action. Use a shared approved continuity board, portrait first frames, and native dialogue only. Write 4–8 lines filling 80%–93.33% of the effective duration. Trim verified unwanted gaps and re-time exact-script captions. Resume existing tasks as recorded.
