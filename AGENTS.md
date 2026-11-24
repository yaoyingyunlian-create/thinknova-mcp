# ThinkNova 视频制作工具包 v3.1.35

新门店片先读取服务端生效修订，只有返回 65 时才启用修订 65。先确认主推项、三条不同卖点、一个观众下一步。缺项只问一次，客户确认后读取并合并项目规则，用 expected_version 保存。没有顾客原话可以用已确认的手册。修订 65 逐段 4～8 句，中文和英文预计占报价时长的 80%～93.33%，先独立盲审再报价。多段共用获授权人物板，使用 9:16 首帧与原生对白。一句台词对应一条原文字幕。已有任务沿用原计划。

工具包只负责制作：素材准备 → ThinkNova 生成与取件 → 拼片 → 字幕 → 质检 → 成片待审包。
发布和定时由客户 AI 助理负责，推荐其原生定时任务配合 Ego Lite。工具包不登录社交账号、不上传作品、不创建系统计划任务。

## 首次使用与更新
1. 用现有 MCP OAuth 连接调用 get_balance、get_toolkit、get_content_rules。会员、预算及素材许可按服务端实际结果判断。
2. 缺工具包自动准备；开工运行 bootstrap.py update --workspace "<客户工作目录>" --json。按返回的 active_toolkit、python 继续；冲突用官方干净副本自动恢复，保留工作目录与客户数据。
3. python bootstrap.py setup --json；之后使用工具包 .venv 的 Python。核心制作不依赖平台登录、Google OAuth、Playwright 或另装 Chromium。Ego Lite 是客户 AI 的外部浏览器，可独立准备。

## 制作
- 门店三项资料缺任一项时，只问缺项。资料齐后复用客户已有资料。多项目必须选定项目，禁止混入另一项目角色和素材；只有关键事实未知或批准预算不可用才暂停收费制作。
- 读取服务器当前主规则和品类表；用户风格偏好在可自定义范围内保留。不可编造地址、价格、案例或素材授权。
- 真实人物、产品、门店优先选授权素材。edit_image 做首帧，animate_image 第一张必须是实际首帧，三视图是补充。最多三张，回读实际采用结果；缺图可在批准预算内准备明确的示意画面。
- 新收费制作前用同一个 .venv Python 运行 `toolkit.py film-preflight`。若失败，先修复该阶段再建新任务。已有任务仍可取件并用 `film --recheck` 复检。
- 明确 ratio=9:16、时长及可用分辨率，规格以服务器报价为准。先 quote_request，再用相同参数、max_credits 和 client_request_id 建单；断网复用原请求号。任务失败后新生成另计费，不自动免费重做。
- 门店片只使用 ThinkNova 生成视频的原生对白。禁止用本地 TTS、macOS say 或替换音轨兜底。原片无声、乱读或漏台词时说明镜头与原任务号，保留预览。裁必要空白时不得截掉台词、伪造时长或导致片长越界。
- 报价前以逐句稿核算片段能说完的时长，并让对白与字幕共用该稿。收到 `FILM_DIALOGUE_OVER_CAPACITY` 时，只改对应片段的台词与字幕，再报价。拼片报告的 `edit_timeline` 给出原素材实剪入出点和剩余接话空档。
- 用 .venv Python 执行 toolkit.py film job.json，或 run-day plan.json --max-credits 已批准金额。对白、已有脚本可提供字幕，不为补字幕重新生成视频。
- 语速与自然停顿记警告；损坏、黑屏、整片无声、严重错配和错误规格仍阻断。识别不可用如实记 unknown，不能虚报回听。保留预览，可从质检续跑，不重复收费制作。
- `delivery_status=delivered` 就把成片、封面和已有文案交给客户。`awaiting_review`、缺发布文案或缺平台授权只影响发布。旧片凭机器质检凭据运行 `film job.json --existing`，未通过的旧预览用 `film job.json --recheck` 接续。先复用原片和原任务，不为补 READY.json 重做。
- 独立术语报告 `speech_review.json` 只用于定位需回听的词，报告的 `publication_ready` 不代表交付状态。复核聚焦报告列出的疑点并保留真实结论。

## 定时与发布交接
先核对客户AI助理支持原生定时和本机执行；不支持则只做手动制作，不宣称任务已登记。
Check that the customer AI supports native timers and local execution; otherwise keep manual production and never claim a task was scheduled.

- 客户 AI 助理用原生定时功能和已有 MCP 连接，按已确认预算报价与生成，再调用 toolkit.py film job.json 制作。沿用原项目、当天请求号及对话；无需试点或设备配对。
- 发布任务由客户 AI 助理另行创建，使用 Ego Lite 核对实际账号、成片版本、文案、披露与现有授权后操作。结果不明先核对已发作品；单个平台失败只影响该平台。
- 不调用已退休的 enable-youtube、tick、tick-produce、tick-publish、install 或平台发布脚本；旧入口只返回迁移说明，不生成、不上传、不安装。遇到旧制作命令或 AUTOMATION_PILOT_NOT_ALLOWED，自动更新原 AI 任务的执行方式，先查当天原任务，旧系统任务可用显式清理命令移除，仅限已知 ThinkNova 任务。
- 本包不持有客户平台 OAuth Token。凭据不写提示词或 memory。只记录任务号、文件位置、用户偏好、确认范围和客户 AI 提供的实际发布结果。

制作前在项目目录为本条作品固定 job.json 路径，运行 `film-events <job>` 取得 run_id，并运行 `film-preflight <job>`。报价与建单支持 film_run_id 时均传此运行号。修订 65 使用只写动作的 prompt，逐句稿放入 dialogue（speaker、text），多段填写 film_segment_count 和相同 continuity_asset_id。仅支持一张时通过 edit_image 将同一人物板合入首帧。取件或生成失败用 `film-events <job> --record-stage download|generation --outcome failed --code 安全错误码` 记录，有任务号和镜头序号就附上。每次制作结束（包括失败）以及巡检时，都通过已有 MCP OAuth 上传待报事件，只确认服务端已接收的 ID。断网后续传。正式成片通过质检时由工具包记录交付事件。

## English
The toolkit produces videos and review packages only. Keep model-generated dialogue, add captions and check media without automatic speech retiming. Pace and natural pauses warn; unusable media and severe mismatch still block. Run toolkit.py film-preflight with the production Python before new paid work. Keep fetching and rechecking existing work if the preflight fails. Preserve previews and resume checks. Use current server rules, approved facts, references and budgets; quote before charging and reuse stable request IDs on retries. Preserve customer data on updates.
Keep one job path and run ID per film. Under revision 65 send visual direction as prompt and the exact approved speaker/text lines as dialogue. Multi-segment calls use the same continuity_asset_id and film_segment_count. Send queued film events through the existing MCP OAuth connection after every attempt, including failures, and during patrol. Only acknowledge IDs returned by the server. Send the film and available assets whenever delivery_status=delivered. Use speech_review.json to identify terms that need listening. Its publication_ready field does not describe delivery status. Use film --existing for a checked legacy output and film --recheck for a failed preview. Reuse the original media and task IDs. Scheduling belongs to the customer's AI assistant. Use existing MCP OAuth for quotes and generation, then toolkit.py film for local production. Publishing uses Ego Lite within confirmed accounts and consent. Keep credentials out of memory and record actual outcomes.
