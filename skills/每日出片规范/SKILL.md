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

访谈只问店主张口能答的，问完你自己填好下面五样，给店主确认一次：

1. **可以直接说的事实**（5～10 条）：这家店解决什么问题、给什么人、主推的 1～3 样、做法上的特别之处（几味料、熬几小时、做多久）、店主自己的经历。每条标「店主已确认」。确认过的以后直接用，⛔ 每条片再问一遍。
2. **不能说的**：只记店主点名的和行业红线（疗效、保证、编的评价）。⛔ 把「待确认」写成默认禁止——没确认的去问，不是不说。
3. **人物三视图**：店里的人固定使用一套授权三视图。每条片换一个虚构顾客，同一条片内用同一套顾客三视图。按「镜头提示词」核对每段实际采用的参考。
4. **到店片收尾与主页**：最后一句由店里的人说一个已核实的位置提示或预约动作，二选一。店名与这项信息进入字幕和片尾叠字。完整地址和电话放平台主页简介。
5. **角度表**：把下面七个角度各填一行这家店自己的内容。平时讲痛点、解决什么问题、给谁；价格只在活动周讲。

| # | 角度 | 片型 | 填什么 |
|---|---|---|---|
| 1 | 痛点 | 剧情 | 主角来之前最烦的那件事 |
| 2 | 第一次来 | 剧情 | 主角第一次体验的全过程 |
| 3 | 产品 / 主推项 | 展示 | 这样东西是什么、怎么做出来的 |
| 4 | 误会 | 剧情 | 外行对这一行最常见的一个误会 |
| 5 | 店主故事 | 剧情 | 为什么开这家店 |
| 6 | 适合谁 | 剧情 | 哪种人最该来、来了解决什么 |
| 7 | 常见问题 | 剧情 | 顾客问得最多的一个问题 |

写脚本前按「做法和原因」「看得见的东西」「顾客常遇的小事」盘点已确认事实，分别存到 `shop_profile.confirmed_facts` 的 `methods_and_reasons`、`visible_details`、`customer_situations`。资料足够即按事实写，末尾附缺项。影响准确性或授权的缺项才阻塞对应镜头。排片规则存 `editorial_instructions`，画面外观、风格、禁项存 `visual_constraints`。

新版档案补充 `category`（品类）、`viewer_action`（看完做什么）、`customer_quotes`（原话、来源及公开授权）和 `missing_information`。服装拍上身走动和细节；保健品展示外包装，从已核实的需求和特色讲，避免打开或倒出；美容美发从具体困扰和服务过程讲。缺项列清单，用能核实的资料继续。

## 二、九宫格选题和每日计划

起稿前写三行：具体受众和困扰、已核实的顾客价值、希望观众采取的行动。账号未写自查时，逐项检查：第一句有具体困扰或真实感受、至少两句有顾客好处、有真实顾客体验才引用、不用台词描述可见动作或罗列服务、每条事实可追溯。把脚本意图、自查证据和缺料清单一起交运营。缺顾客原话时略去效果表述，继续能做的片型。
Before drafting, record audience/problem, confirmed benefits and the intended action. Use the project's checklist. Send missing facts to operations, and omit any unsupported experience claim.


店铺档案 editorial 保存至少三项人群、场景、痛点、特色和常见问题，问题含稳定 ID 与次数，另记录生意类型和活动日期。每周用三行（人群、痛点或问题）和三个特色列形成九宫格，挑七格。相邻两天换行、列和拍法，每周至少四种拍法、至少两条回答前三热门问题。同格查 28 天，开场句、开场画面和同格同拍法查 56 天。活动到期排除价格和过期主题。

拍法可选顾客心里话、剧情、趣味剧情、探店、过程揭秘、前后对比、问答、产品特写、折扣和一天或一单。用 python toolkit.py validate-week 校验选题池，每天只准备一条可执行日计划。工具包负责报价、取件和拼片，异常写入运行诊断。

## 三、片型与画内对白

账号没有指定时采用内置七片型和对白写作默认值。新版普通产品和服务片两段各 15 秒，每段一问一答、3～4 句，默认 55～62 字。原样记录对白并同步字幕。参考图依照「镜头提示词」预检。

## 四、制作与提交

1. 报价与建单都带 `duration_seconds: 15` 和 `ratio: "9:16"`，逐段检查三张参考图实际生效。预算不足时指出差额。
2. 保留两个人在场的真实互动。第一秒有动作，台词遵循当前账号规则并通过当前片型校验。用工具包拼片及检查，把成片、逐段对白、实际参考图和检查原文送审。
3. 店铺、产品及授权事实从当前项目读取。对白不念价格和带单位的数字。字幕和片尾信息由工具包叠加。

## 五、标题和文案

- 标题 = 这条片讲的那件具体的事 + 地点词。⛔ 只有氛围没有信息的标题。
- 正文：第一行重复开场那句；第二行一个具体信息；活动周加起止日期。联系方式按客户规则，默认只写「主页有联系方式」。
- 各平台分别写，写法见「门店成片」第六节的表。
- AI 标注：只打开平台自带的 AI 标签开关，⛔ 在每条正文里再写一遍免责声明。

## 六、样片审核与后续发布

首条样片与各平台发布信息一起请店主确认。客户可在这一步明确开启无人值守发布。已有有效授权的合格成片按授权的账号、平台、预算和排期执行。普通发布仍按本条作品确认。

## English summary

Use the project's editorial rules. Reuse the approved staff turnaround, and choose a different customer for each film. For a visit, have the staff say one verified location cue or booking action; keep the full address and phone in the profile. Quote all segments and verify applied references. Review the first film and platform copy with the customer. Later qualifying films follow the active unattended grant, when enabled.
