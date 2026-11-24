# ThinkNova 视频制作工具包 v3.1.35

新门店片按修订 64 制作。主推项、三条不同卖点和收尾动作由客户确认后写进项目规则。新脚本逐段 4–6 句，盲审通过再报价，字幕使用逐句原文。服务器日计划携带与台词摘要绑定的盲审结果；本机自带计划可用 Codex 独立盲审和限一次改稿。已有任务按原规则续跑。

For new revision 64 store films, confirm the product or service, three distinct selling points, and the viewer’s next action before quoting. Use 4–6 spoken lines per segment and an independent dialogue review. Subtitles use the exact script text and spoken timestamps. Existing tasks resume under their original rules.

工具包交付成片与待审包。自动发布推荐使用 **客户 AI 助理的原生定时任务 + Ego Lite**；工具包不再发布、登录社交账号或注册电脑系统任务。

## 安装与制作

从官方 GitHub 或 Gitee main 获取工具包，运行 `python bootstrap.py setup --json`。后续安全更新使用 `python bootstrap.py update`；保留客户规则、记忆、素材、登录态和作品。安装不再下载发布用 Playwright Chromium 或 Google OAuth SDK。

核心依赖为 Python 3.10+、FFmpeg/FFprobe、libass 和中文字体；字幕识别使用本机 Whisper。Ego Lite 由客户 AI 助理独立使用，不影响核心制作。

使用虚拟环境 Python：

```text
python toolkit.py film-preflight
python toolkit.py film job.json
python toolkit.py run-day plan.json --max-credits APPROVED_BUDGET
python toolkit.py doctor --json
```

新收费任务前用 `film-preflight` 检查 FFmpeg 渲染、字幕和本地转写运行时。单段已确认存在原生对白缺陷时，自动流程暂停后续新建单，已有素材保留。

Run `film-preflight` before new paid jobs to check rendering, subtitles and the local speech runtime. Confirmed dialogue defects stop new requests while preserving existing media.

只使用 ThinkNova 生成视频的原生对白。门店片禁止本地合成、静音或替换音轨；裁边界空白，添加字幕和片尾叠字。语速与自然停顿提示，不单独否决整片。损坏、黑屏、整片无声、严重错配和错误规格仍拦截。缺字幕时先复用已知台词，未知时保留预览并说明缺项。新默认策略 `native_dialogue_v1`，原58号灰度配置仍兼容。

`publish/dispatch.py --dry` 只准备本地文案与文件清单；其 `--execute` 及旧平台上传、登录脚本均已退休。实际发布由客户 AI 助理在 Ego Lite 完成，不使用本包发布器。

## 自动修复旧安装

开工时从已安装工具包运行 `python bootstrap.py update --workspace "<客户工作目录>" --json`。命令在原目录尝试安全更新；遇到源码冲突或完整性错误时自动准备官方干净副本。按返回的 active_toolkit 和 python 继续，同一个客户工作目录和执行记录保持原位。两个官方源都不可达时，验证原副本本机制作可用后继续，版本显示未知。

遇到 AUTOMATION_PILOT_NOT_ALLOWED 或旧制作入口时，原 AI 定时任务就地改用现有 MCP 连接报价、生成、取件，再调用 toolkit.py film。保留时间、对话和原请求号，先查当天已有任务再决定是否生成。

## 成片诊断与自动复检

制作和巡检使用同一份 job.json。工具包记录失败原因，自动尝试字幕修复或原预览复检。可恢复的下载故障由 AI 助理回查原任务并取回原产物。

每段取件后检查原生音轨，并按原任务号和素材摘要保留已确认的逐句时间戳。字幕缺项时仅复查对应音频区间；转写不可用时保留原声预览，并返回镜头和未对齐的句子序号。补拍只处理有缺陷证据的镜头，并沿用已批准的预算。

After download, the toolkit checks the original audio and saves line timings against the original task and source hash. It retries the affected audio window for missing timings and retains a playable preview with the original audio if recognition is unavailable. Retakes require evidence for the affected clip and an approved budget.

助理在开工前运行 `toolkit.py film-events job.json` 获取运行号，运行 `toolkit.py film-preflight job.json` 记录预检故障，报价和建单使用同一 `film_run_id`（服务器支持时）。制作结束时，即使失败，助理也运行 `toolkit.py film-events job.json`，使用 MCP 的 report_film_events 提交 events，随后只对服务端返回的 acknowledged ID 使用 `toolkit.py film-events job.json --ack EVENT_ID`（多个 ID 重复传入 --ack）。断网时留在本地，下次巡检继续递送。日志仅包含结构化诊断字段。

Use the same job path and film run ID for preflight, quotes, creation, and incident reporting. Relay pending events after every attempt and acknowledge only IDs returned by MCP. The toolkit records delivery only after the final file matches its quality receipt.

## 成片交付与发布确认

机器质检通过后，delivery_status=delivered 表示可交付成片。语音和画面复核列在 review_requirements，平台文案或授权待补列在 publication_status。先交付成片，再按需处理发布。若旧待审预览误用通用片型，`film job.json --recheck` 校验预览摘要后，从本机原镜头按门店片型重新检查，缺镜头时返回序号，沿用原任务取件。

When rechecking an old store-film preview created under the generic film profile, the toolkit validates the preview hash and reuses the original local clips under the store profile. Missing sources are reported by clip number.

只改文案或封面可再次运行 film，复用同一成片。旧安装已有成片和匹配的 .film.json 凭据时，用 python toolkit.py film job.json --existing 生成当前交付包，不重新渲染或生成。

## 客户 AI 定时任务

由客户 AI 助理的原生定时任务复用现有 MCP OAuth 连接。按客户已确认的预算报价、生成与取件，再用工具包制作成片。无需申请试点、再次绑定设备或输入配对码。

旧系统任务的 tick / tick-produce / tick-publish 入口不再执行。将已有 AI 助理任务的制作入口改为 MCP 报价、生成、取件及工具包拼片，发布继续走 Ego Lite。旧系统任务不会被悄悄删除；需要时显式清理已知 ThinkNova 任务，客户作品和登录态保留。

发布前按客户现有确认范围核对作品、账号、标题、正文、标签、平台与时间；首次样片待审核。单个平台登录失败仅阻塞该平台，未知结果先核验，避免重复发布。

### 发布任务原地升级

制作、巡检和发布使用同一个客户工作目录。更新原定时任务的内容，沿用原时间和对话。在发布日之前把每个平台已确认的计划写入 publication-plan.json，并运行 `toolkit.py publication-handoff WORKSPACE publication-plan.json`。把返回的 reports 逐条通过 report_film_publication 上报。更新计划时，对已移除的目标先用原计划资料上报 confirmed=false。

每个计划记录 project_key、local_date 和 targets。每个目标记录 target_account、confirmed、UTC 格式的 due_at、window_ends_at，并按已经确认的发布授权填写 approval。首次或逐版审核使用 scope=version 和实际 film_sha256、copy_sha256。已授权日常发布使用 scope=standing，包含 first_film_reviewed=true、requires_per_version_review=false、content_review_pending=false。成片后填入 review-package.json 返回的 run_id，再同步一次排期。

实际到点后使用 Ego Lite 核对当前平台账号，运行 `toolkit.py publication-handoff WORKSPACE publication-plan.json --package REVIEW_PACKAGE --platform PLATFORM --observed-account ACCOUNT`。只有 ready_to_publish 才上传当前成片。submitted_unverified 时先核对平台作品，已发布则用 browser_receipt.py record 记录真实链接和时间。确认未发且仍在窗口内时，才以 --verified-absent 获取一次重试。上传结果从 browser_receipt.py 的 upload_report 上报，failure_reason 使用稳定错误码，例如 LOGIN_REQUIRED。上报失败时保留原回执，下一次巡检用 sync 重读后提交。

### 已授权补拍

paid_retake 默认关闭。启用后，只对原质检报告定位到的严重故障准备用一次补拍。决策文件记录 authorized、remaining_approved_credits、segment_index、reason_code、tool 和已核对的 arguments。运行 `toolkit.py film-replacement job.json replacement-decision.json` 获取只读报价请求，调用 get_balance 后用 --quoted-credits 传回报价金额。收到 ready_to_submit 后，由 AI 助理使用返回的稳定 client_request_id 和 max_credits 提交，断网续跑复用同一请求号。取得结果后把实际 charged_credits 记录到原制作任务，并用 film-events JOB --record-stage generation --outcome passed --code FILM_PAID_RETAKE --task-no TASK_ID 上报。后台只统计该补拍请求号对应的实际结算积分。用新片重新质检。工作目录保留已用过的补拍授权和请求。

## English

This is a video-production toolkit. Install with bootstrap.py setup --json, make and check videos with toolkit.py film or run-day, and deliver a review package. Store films must retain the original ThinkNova audio. Do not use local TTS, macOS say, muting, or replacement audio. Minor pace and pause deviations warn. Bad media, wholly silent films and severe dialogue mismatch still block.

Before quoting, check that the dialogue fits the requested duration. If FILM_DIALOGUE_OVER_CAPACITY identifies a segment, shorten its dialogue and update its captions together. The edit_timeline report records source in/out points and the remaining dialogue gap at each join.

Scheduling and publishing use the customer's AI assistant's native timers and Ego Lite. The toolkit installs no OS tasks and no longer supplies active upload/login implementations. Old commands return migration guidance. Reuse MCP OAuth for quotes, generation and downloads, then use the toolkit to assemble the video. Keep the confirmed budget and existing idempotency keys. No pilot or device pairing is needed. No platform OAuth or browser login is required for creation. Preserve customer memory, assets, platform sessions and work during upgrades.
