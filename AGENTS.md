# ThinkNova 视频制作工具包 v3.1.28

工具包只负责制作：素材准备 → ThinkNova 生成与取件 → 拼片 → 字幕 → 质检 → 成片待审包。
发布和定时由客户 AI 助理负责，推荐其原生定时任务配合 Ego Lite。工具包不登录社交账号、不上传作品、不创建系统计划任务。

## 首次使用与更新
1. 用现有 MCP OAuth 连接调用 get_balance、get_toolkit、get_content_rules。会员、预算及素材许可按服务端实际结果判断。
2. 缺工具包自动准备；开工运行 bootstrap.py update --workspace "<客户工作目录>" --json。按返回的 active_toolkit、python 继续；冲突用官方干净副本自动恢复，保留工作目录与客户数据。
3. python bootstrap.py setup --json；之后使用工具包 .venv 的 Python。核心制作不依赖平台登录、Google OAuth、Playwright 或另装 Chromium。Ego Lite 是客户 AI 的外部浏览器，可独立准备。

## 制作
- 已知产品或服务就继续，复用客户资料。多项目必须选定项目，禁止混入另一项目角色和素材；只有关键事实未知或批准预算不可用才暂停收费制作。
- 读取服务器当前主规则和品类表；用户风格偏好在可自定义范围内保留。不可编造地址、价格、案例或素材授权。
- 真实人物、产品、门店优先选授权素材。edit_image 做首帧，animate_image 第一张必须是实际首帧，三视图是补充。最多三张，回读实际采用结果；缺图可在批准预算内准备明确的示意画面。
- 明确 ratio=9:16、时长及可用分辨率，规格以服务器报价为准。先 quote_request，再用相同参数、max_credits 和 client_request_id 建单；断网复用原请求号。任务失败后新生成另计费，不自动免费重做。
- 保留视频模型原生对白，不默认另做 TTS，不按语速自动调速。裁必要空白时不得截掉台词、伪造时长或导致片长越界。
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

制作及巡检调用 film-events，向 MCP report_film_events 递送并仅确认已接收的 ID。断网后补传。

## English
The toolkit produces videos and review packages only. Keep model-generated dialogue, add captions and check media without automatic speech retiming. Pace and natural pauses warn; unusable media and severe mismatch still block. Preserve previews and resume checks. Use current server rules, approved facts, references and budgets; quote before charging and reuse stable request IDs on retries. Preserve customer data on updates.
Send the film and available assets whenever delivery_status=delivered. Use speech_review.json to identify terms that need listening. Its publication_ready field does not describe delivery status. Use film --existing for a checked legacy output and film --recheck for a failed preview. Reuse the original media and task IDs. Scheduling belongs to the customer's AI assistant. Use existing MCP OAuth for quotes and generation, then toolkit.py film for local production. Publishing uses Ego Lite within confirmed accounts and consent. Keep credentials out of memory and record actual outcomes.
