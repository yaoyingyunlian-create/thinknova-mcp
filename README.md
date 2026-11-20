# ThinkNova 视频制作工具包 v3.1.24

工具包交付成片与待审包。自动发布推荐使用 **客户 AI 助理的原生定时任务 + Ego Lite**；工具包不再发布、登录社交账号或注册电脑系统任务。

## 安装与制作

从官方 GitHub 或 Gitee main 获取工具包，运行 `python bootstrap.py setup --json`。后续安全更新使用 `python bootstrap.py update`；保留客户规则、记忆、素材、登录态和作品。安装不再下载发布用 Playwright Chromium 或 Google OAuth SDK。

核心依赖为 Python 3.10+、FFmpeg/FFprobe、libass 和中文字体；字幕识别使用本机 Whisper。Ego Lite 由客户 AI 助理独立使用，不影响核心制作。

使用虚拟环境 Python：

```text
python toolkit.py film job.json
python toolkit.py run-day plan.json --max-credits APPROVED_BUDGET
python toolkit.py doctor --json
```

默认保留模型原声，不另做 TTS、不自动调速；裁边界空白，添加字幕和片尾叠字。语速与自然停顿提示，不单独否决整片。损坏、黑屏、整片无声、严重错配和错误规格仍拦截。缺字幕时先复用已知台词，未知时保留预览并说明缺项。新默认策略 `native_dialogue_v1`，原58号灰度配置仍兼容。

`publish/dispatch.py --dry` 只准备本地文案与文件清单；其 `--execute` 及旧平台上传、登录脚本均已退休。实际发布由客户 AI 助理在 Ego Lite 完成，不使用本包发布器。

## 客户 AI 定时任务

由客户 AI 助理的原生定时任务复用现有 MCP OAuth 连接。按客户已确认的预算报价、生成与取件，再用工具包制作成片。无需申请试点、再次绑定设备或输入配对码。

旧系统任务的 tick / tick-produce / tick-publish 入口不再执行。将已有 AI 助理任务的制作入口改为 MCP 报价、生成、取件及工具包拼片，发布继续走 Ego Lite。旧系统任务不会被悄悄删除；需要时显式清理已知 ThinkNova 任务，客户作品和登录态保留。

发布前按客户现有确认范围核对作品、账号、标题、正文、标签、平台与时间；首次样片待审核。单个平台登录失败仅阻塞该平台，未知结果先核验，避免重复发布。

## English

This is a video-production toolkit. Install with bootstrap.py setup --json, make and check videos with toolkit.py film or run-day, and deliver a review package. Preserve original model dialogue; do not default to TTS or automatic pace adjustment. Minor pace and pause deviations warn. Bad media, wholly silent films and severe dialogue mismatch still block.

Scheduling and publishing use the customer's AI assistant's native timers and Ego Lite. The toolkit installs no OS tasks and no longer supplies active upload/login implementations. Old commands return migration guidance. Reuse MCP OAuth for quotes, generation and downloads, then use the toolkit to assemble the video. Keep the confirmed budget and existing idempotency keys. No pilot or device pairing is needed. No platform OAuth or browser login is required for creation. Preserve customer memory, assets, platform sessions and work during upgrades.
