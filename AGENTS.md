# ThinkNova 自动化工具包 · 给 AI 助手的操作说明（AGENTS.md）

> 你是用户的 AI 助手（Claude / Codex / ChatGPT 等）。只有在用户明确同意加载后，才使用本工具包；不能因已连接 MCP 就自动加载。ThinkNova MCP 负责账户规则与图像/视频生成；渲染、检查、平台登录和发布只能在用户自己的电脑、文件和平台账号上运行。
> You are the user's AI assistant. Use this toolkit only after the user explicitly agrees to load it. ThinkNova MCP handles account-aware rules and generation; rendering, platform login, and publishing run locally with the user's own files and accounts.

## 0. 首次加载后：先了解目标，再准备环境
- 每次会话开始，读取本地 `manifest.json` 的 `revision`，调用 `check_toolkit_update(installed_revision=...)`。尚未安装时省略参数并主动询问是否下载安装工具包；发现 `update_available=true` 时向用户展示新版并询问是否更新，用户拒绝则继续使用旧版。不要把联网失败说成“已经最新”。
- 用户同意安装或更新后调用 `get_toolkit(user_confirmed=true)`，以 MCP 返回的 SHA-256 校验 ZIP，使用 `python update.py --url <download_url> --sha256 <sha256> --destination <新目录> --user-confirmed` 安装到独立目录。旧版的记忆、账号登录态与文件继续保留，迁移前必须告知用户。
- 安装完成必须运行 `python toolkit.py verify`、`python toolkit.py doctor`，逐项修复缺少的文件、Python 3.10+、Node 18+、ffmpeg/ffprobe、Playwright 与 Chromium；检查未通过不得宣称安装成功。没有本地命令执行能力的 AI 客户端应明确提示改用具有本机执行能力的助手。
- 不要一上来让用户研究命令或脚本。先用简短访谈了解：① 想达到的效果（获客、品牌曝光、互动、引流或转化）② 目标受众 ③ 想经营的平台（可多选）④ 风格、语言和禁忌 ⑤ 现有素材及授权 ⑥ 发前审核和发布偏好。已经回答的内容不要重复问；信息不足时再一次追问一个关键项。
- 根据回答给出简短内容方案（平台、内容类型、频率、主题/钩子、素材和审核节点），获得同意后再开始生成或本机操作。
- 支持平台仅限本包实际脚本：YouTube、TikTok、小红书、抖音、Facebook（Business Suite 主页 Reels）、Instagram（Reels 或图片轮播）、LinkedIn（纯文字）和 X。不得承诺未列平台。
- 装环境：Python 3.10+、ffmpeg、Node.js 18+；在本目录运行 `pip install -r requirements.txt` 和 `python -m playwright install chromium`。
- 首次本机准备后运行 `python toolkit.py init`；它只会在 `memory.md` 不存在时创建本地记忆，绝不覆盖既有记忆。每次开始先读本地 `memory.md`，再调用 `get_balance`、`get_content_rules`。本地记忆绝不上传或通过 MCP 返回。
- 需要每天自动回收已发布内容的只读 24/48 小时数据时，用户确认后运行 `python toolkit.py install-schedule`；该定时任务只采集指标、归档记忆和提示待办，不能生成、扣费或发布。Windows/macOS/Linux 均有本机实现，卸载用 `python toolkit.py uninstall-schedule`。
- 要做动画 / 字幕版式时，用开源的 HyperFrames：`npx skills add heygen-com/hyperframes`（模板在 `render/hyperframes/`）。
- 本目录 `skills/` 里是写脚本用的方法（开场钩子、全片留存节奏、口语台词、小红书笔记）；Claude 可放进 `.claude/skills/`，其他助手直接读文件。
- ⛔ 你不碰用户的密码。各平台第一次发布前，运行 `publish/<平台>/login.py`，让用户自己在弹出的浏览器里登录一次，登录状态存在本机。

## 1. 查身份和积分
调用 `get_balance`。
- 返回 `MCP_PLAN_REQUIRED`：把工具返回的升级说明和链接原样告诉用户，停在这里。
- 正常：记下可用积分、当天额度、并发上限；积分不够当次计划时先告诉用户。

## 2. 规矩（每次开工先读）
调用 `get_content_rules`。
- 使用返回的 `effective_rules` 作为默认有效规矩；`rules` 为空时不代表没有默认审核方式。默认 `review_mode=pre_publish`，即生成前说明计划与积分，真实发布前才请求用户确认。
- **没有自定义规矩**：承接首次访谈中已得到的信息，只补缺失项；用户说不清的给 2–3 个选项让他挑：
  ① 店 / 产品是什么和目标（获客、曝光、互动、引流、转化）② 受众 ③ 主角是谁（固定角色还是不出人）④ 风格和语言 ⑤ 发哪些平台 ⑥ 每周几条、几点发 ⑦ 不能出现的内容 ⑧ 发之前要不要先给他看 ⑨ 可以用的素材和授权（让用户传图，见第 3 步）。
  定完调用 `save_content_rules` 保存。
- **有规矩**：按规矩直接做，不再重复问。用户要改哪项，改完再 `save_content_rules`。

## 3. 素材
- 用户给的图：`create_reference_upload` 申请上传地址 → 按返回的方式上传原图 → `complete_reference_upload` 拿 `reference_asset_id`。公开图片链接用 `import_reference_url`。
- 参考图要对位：人物位放人、场景位放店、产品位放产品。有真人脸、儿童、私人照片的，先问用户能不能用。一次生成最多传 3 张，按角色、场景、产品排序。

## 4. 做视频（固定角色系列短片按 `rules/固定角色系列短片.md` 做）
1. 用 `skills/` 写本集脚本和镜头表（每镜：场景、动作、台词、首帧来源）。
2. 每镜首帧：`generate_image` / `edit_image`，参考素材使用 `reference_asset_ids`（最多 3 张；旧客户端可用单个 `reference_asset_id`）。
3. 每镜动起来：`animate_image`，台词直接写进提示词，画面和声音一起出。创建结果中的 `reference_handling` 必须回读：`all_applied` 才表示全部参考图生效；`first_only` 表示模型只使用了首图，不能宣称角色与场景均已锁定。
4. 等结果：`wait_task`（最多等 3 秒，返回当前状态）或 `get_task`；**同一意图重试要沿用原来的 `client_request_id`**，⛔ 因为等得久就重复建单。
5. 成功后 `get_result` 下载成片。

## 5. 拼片和检查（本机运行）
- 拼片、字幕：`render/hyperframes/` 模板或你自己的剪辑；字幕用 `render/captions.py`。
- 统一音量：`python render/loudnorm.py <in.mp4> <out.mp4>`（-14 LUFS）。如需交付 1080×1920，可本机转码，但必须如实说明这不会提升低分辨率生成源的细节；优先使用 MCP 实际交付规格。
- 发前检查：`python render/check.py <video.mp4>`，全过才发。

## 6. 发布（仅在用户本机运行）
- 每条视频写一个 `job.json`（格式见 `job.example.json` 和 `README.md`）：视频、标题、文案、话题、AI 内容声明、定时时间。
- 先演练再真发。TikTok / 小红书 / 抖音：`python publish/<平台>/publish.py job.json --dry` → 去掉 `--dry` 正式预约；YouTube：`python publish/youtube/upload.py job.json`；Facebook / Instagram / LinkedIn / X：`python publish/<平台>/publish.py --job job.json --dry` → 把 `--dry` 换成 `--execute` 才会真发。
- 无论审核偏好如何，真实发布、改定时和再次发布都要取得用户当次明确确认；只获准演练时只运行 `--dry`。远程 MCP 不会、也不能操作客户电脑上的文件、浏览器或登录态。
- 规矩写了「发前给我看」：先把成片和文案发给用户，用户点头再发。
- 支持平台：TikTok、小红书、抖音、YouTube、Facebook（Business Suite 主页 Reels）、Instagram、LinkedIn（纯文字）、X。后四个的命令统一为 `publish/<平台>/publish.py --job job.json --dry|--execute`，字段见 README 第 3 节。
- 发完回读一次：平台上定时时间、标题、AI 声明都对上才算排好。
- YouTube / TikTok 发布后，把内容 ID、公开链接和发布时间登记为本地数据采集目标：`python analytics.py register ...`；24/48 小时采集失败只写入本地记忆，绝不自动重发。

## 7. 出错时
- 生成失败：原样重提 1 次；还失败就停下，把任务号和报错告诉用户，⛔ 连刷。不要用末帧定格伪造镜头时长；改为重做镜头或本地后期编辑。
- 平台登录失效：请用户重新运行 `login.py` 登录。
- 不确定的事（要不要用某张图、要不要改规矩）：问用户，不猜。

---

## English summary
At the start of every session call `check_toolkit_update` with the installed manifest revision. Offer installation when missing; ask before updating. After consent use `get_toolkit`, verify its SHA-256, install into a NEW folder, preserve local memory/sessions, then run `toolkit.py verify` and `toolkit.py doctor`. A failed check is not a successful installation.
1. After explicit toolkit consent, begin with a short interview: outcome, audience, supported platforms, style/constraints, authorised assets, and review/publishing preference. Propose a short plan before generation or local actions.
2. `get_balance` — if `MCP_PLAN_REQUIRED`, relay the upgrade message and stop.
3. `get_content_rules` — if empty, interview only for missing information and `save_content_rules`.
4. Upload references with `create_reference_upload` → upload → `complete_reference_upload` (or `import_reference_url`).
5. Script with `skills/`; first frames with `generate_image`/`edit_image`; animate each shot with `animate_image` (dialogue inside the prompt); poll with `wait_task`/`get_task` reusing `client_request_id`; download with `get_result`.
6. Render/captions → `render/loudnorm.py` → `render/check.py` locally.
7. Publish locally only: supported platforms are YouTube, TikTok, Xiaohongshu, Douyin, Facebook, Instagram, LinkedIn, and X. Start with dry run; require explicit confirmation before real publication. Never handle passwords or claim MCP controls local files/accounts.
