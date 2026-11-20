# ThinkNova 视频制作工具包 v3.1.22

工具包只负责制作：素材准备 → ThinkNova 生成与取件 → 拼片 → 字幕 → 质检 → 成片待审包。
发布和定时由客户 AI 助理负责，推荐其原生定时任务配合 Ego Lite。工具包不登录社交账号、不上传作品、不创建系统计划任务。

## 首次使用与更新
1. 用现有 MCP OAuth 连接调用 get_balance、get_toolkit、get_content_rules。会员、预算及素材许可按服务端实际结果判断。
2. 缺工具包自动准备；后续 bootstrap.py update 自动安全更新。保留客户工作目录、素材、memory、登录态和作品；源码冲突先用官方干净副本恢复，不覆盖客户改动。
3. python bootstrap.py setup --json；之后使用工具包 .venv 的 Python。核心制作不依赖平台登录、Google OAuth、Playwright 或另装 Chromium。Ego Lite 是客户 AI 的外部浏览器，可独立准备。

## 制作
- 已知产品或服务就继续，复用客户资料。多项目必须选定项目，禁止混入另一项目角色和素材；只有关键事实未知或批准预算不可用才暂停收费制作。
- 读取服务器当前主规则和品类表；用户风格偏好在可自定义范围内保留。不可编造地址、价格、案例或素材授权。
- 真实人物、产品、门店优先选授权素材。edit_image 做首帧，animate_image 第一张必须是实际首帧，三视图是补充。最多三张，回读实际采用结果；缺图可在批准预算内准备明确的示意画面。
- 明确 ratio=9:16、时长及可用分辨率，规格以服务器报价为准。先 quote_request，再用相同参数、max_credits 和 client_request_id 建单；断网复用原请求号。任务失败后新生成另计费，不自动免费重做。
- 保留视频模型原生对白，不默认另做 TTS，不按语速自动调速。裁必要空白时不得截掉台词、伪造时长或导致片长越界。
- 用 .venv Python 执行 toolkit.py film job.json，或 run-day plan.json --max-credits 已批准金额。对白、已有脚本可提供字幕，不为补字幕重新生成视频。
- 语速与自然停顿记警告；损坏、黑屏、整片无声、严重错配和错误规格仍阻断。识别不可用如实记 unknown，不能虚报回听。保留预览，可从质检续跑，不重复收费制作。
- 交付成片、联系表、对白、素材引用、质检和逐平台文案。按实际质检凭据与摘要判断，不以 READY.json 单个文件决定是否有成片。首条作品及发布信息待客户审核。

## 定时与发布交接
先核对客户AI助理支持原生定时和本机执行；不支持则只做手动制作，不宣称任务已登记。
Check that the customer AI supports native timers and local execution; otherwise keep manual production and never claim a task was scheduled.

- 客户 AI 助理使用自身定时功能，定时调用单次制作入口 automation.py produce-once；assistant-schedule 只返回制作任务建议，不安装任务。
- 发布任务由客户 AI 助理另行创建，使用 Ego Lite 核对实际账号、成片版本、文案、披露与现有授权后操作。结果不明先核对已发作品；单个平台失败只影响该平台。
- 不调用已退休的 enable-youtube、tick、tick-produce、tick-publish、install 或平台发布脚本；旧入口只返回迁移说明，不生成、不上传、不安装。已有 AI 定时任务需改指新入口，旧系统任务可用显式清理命令移除，仅限已知 ThinkNova 任务。
- 本包不持有客户平台 OAuth Token。凭据不写提示词或 memory。只记录任务号、文件位置、用户偏好、确认范围和客户 AI 提供的实际发布结果。

## English
The toolkit produces videos and review packages only. Keep model-generated dialogue, add captions and check media without automatic speech retiming. Pace and natural pauses warn; unusable media and severe mismatch still block. Preserve previews and resume checks. Use current server rules, approved facts, references and budgets; quote before charging and reuse stable request IDs on retries. Preserve customer data on updates.
Scheduling belongs to the customer's AI assistant. Its native timer can invoke automation.py produce-once; assistant-schedule only returns production suggestions. Publishing belongs to that assistant through Ego Lite, within confirmed accounts and consent. Never run retired toolkit publishers or install OS tasks. Old timer commands do nothing and return migration guidance. No Google Desktop OAuth or platform login is needed to create videos. Do not store platform credentials in memory; record actual outcomes without claiming unverified publication.
