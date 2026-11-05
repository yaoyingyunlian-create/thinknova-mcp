# ThinkNova 自动化工具包 (ThinkNova Automation Toolkit) - render & publish

> 给 AI 助手：先读 AGENTS.md。For AI assistants: read AGENTS.md first.

安装体检：`python bootstrap.py setup --json`；安装完成后用 `.venv` Python 执行 `python toolkit.py doctor --json --online`。报告区分本机可运行与账户/规则/平台未知，Chromium 会实际启动检查；失败不算全就绪。后续更新会重新启动新版 setup。Windows 受控自动化试点见 [AUTOMATION.md](AUTOMATION.md)，默认关闭，不替代现有只读定时维护。

Installation diagnostics: setup --json and toolkit.py doctor --json --online provide structured results, real Chromium launch checks and explicit unknown remote states. Updates restart the new setup process. The opt-in controlled Windows pilot is documented separately in AUTOMATION.md; existing users are never enrolled automatically.

自动修复：`python bootstrap.py repair` 会恢复缺失文件并安装缺失工具、Python 依赖与 Chromium，最后重新检查。机器缺少 Git/Python 时使用 `install.ps1`（Windows）或 `install.sh`（macOS/Linux）。没有包管理器、安装权限或网络时返回具体错误，恢复条件后可重复执行。
Automatic repair: run `python bootstrap.py repair`; missing tracked files and dependencies are repaired and rechecked. Use the native install script if Git/Python is missing. Package-manager, permission and network failures remain explicit and never count as a successful installation.

源码仓库：[thinknova-mcp](https://github.com/yaoyingyunlian-create/thinknova-mcp)。每次开工调用 MCP
`check_toolkit_update(installed_revision=manifest.json 中的 revision)`；第一次无安装时省略参数。
首次会员连接后自动调用 `get_toolkit()`，通过 HTTPS 克隆此仓库并运行 `python bootstrap.py setup`。
后续运行 `python bootstrap.py check` 直接检查 GitHub；发现新版后才询问用户，同意后执行
`python bootstrap.py update --user-confirmed`。更新保留本地记忆及登录态，代码修改或非快进更新会被拒绝。

Toolkit source is maintained in this independent repository. First installation automatically clones
the HTTPS repository and runs bootstrap.py setup. Later sessions use bootstrap.py check against GitHub;
ask before applying an update. Preserve local data and verify all dependencies before declaring readiness.

Scripts to finish and publish the images / videos you create with the ThinkNova MCP in your own
AI assistant (ChatGPT, Claude, ...). Everything runs on **your own computer** with **your own
accounts**. The toolkit does not create content and does not judge content: it only renders,
checks and publishes what you give it.

## AI assistant workflow / 首次自动安装

An MCP host may show ThinkNova's connection instructions, but it cannot force an assistant to
load this package or to act on it. First setup should run automatically after eligible OAuth; the
assistant should first ask briefly about the intended outcome (lead generation, awareness,
engagement, traffic, or conversion), audience, supported target platforms, style and constraints,
authorised assets, and review/publishing preference. It should then propose a short content plan
before asking ThinkNova MCP to generate media or asking the user to run local commands.

ThinkNova MCP provides generation and account rules only. Rendering, quality checks, browser
login, dry runs, scheduling, and publishing run on the customer's local computer with their own
files and accounts. A real publication always requires explicit confirmation at that time. The
supported scripts are YouTube, TikTok, Xiaohongshu, Douyin, Facebook, Instagram, LinkedIn, and X;
do not infer support for other platforms.

中文：首次连接自动拉取并初始化，不再询问下载。检查到新版才询问更新。加载后读取账户规则，仅补问缺失的目标与素材信息。真实发布需要当次明确确认。

> 中文说明见文末。

---

## 1. Install

| What | Version | Why |
|---|---|---|
| Python | 3.10+ | all scripts |
| ffmpeg (+ ffprobe) | any recent build, on PATH | loudness, subtitles, checks |
| Node.js | 18+ | HyperFrames (HTML -> video) |
| Playwright + Chromium | see below | browser automation for TikTok / Xiaohongshu / Douyin / Facebook / Instagram / LinkedIn / X |

```bash
pip install -r requirements.txt
python -m playwright install chromium
ffmpeg -version          # must print a version
node --version           # must be v18 or newer
```

`faster-whisper` in requirements.txt is optional (local speech-to-text for subtitles and the
speech-gap check). Skip it if you already have subtitles.

本地记忆与只读数据回收：首次运行 `python toolkit.py init`；检查下载包完整性用
`python toolkit.py verify`；需要每天回收 YouTube/TikTok 的 24/48 小时数据时，经用户确认后运行
`python toolkit.py install-schedule`。它不会生成或发布内容。超过记忆阈值时运行
`python toolkit.py archive`。草稿候选只可先用 `python drafts.py list` 展示；删除本地候选记录必须显式
`python drafts.py purge --confirm <id>`，平台草稿仍需在平台页面手动确认删除。

定时任务每天10点按本机时区执行 `toolkit.py maintenance`：只读采集、保存完整归档快照、仅压缩历史事件并生成 `reminders.txt`。它不启动 AI 会话，也不自动扣费或发帖。旧格式记忆无“历史事件”节时仅备份，不自动删段；初始模板不会覆盖已有记忆。其他活动章节即使超过阈值也保留，需助手保留快照后人工整理。日志和状态写入有进程锁；其他 AI 编辑器仍应避免同时改同一文件。

Scheduled maintenance runs at 10:00 local time: collect metrics, archive history with full snapshots, and write local reminders. It never wakes an AI session or generates/publishes content. Active memory is retained; legacy files are backed up without truncation. Use the template's task/billing and publication-approval records to preserve traceability.

旧用户更新后，setup 会自动执行 `toolkit.py migrate-memory`：先备份，再添加缺少的章节，保留旧内容。也可单独运行此命令。旧系统定时任务的命令不会随源码更新自动变化，需要先卸载旧任务、说明新维护范围后再由用户确认安装。维护提醒写在本地 reminders.txt，不发送邮件或社媒消息。

After upgrading, setup runs `toolkit.py migrate-memory` to snapshot existing memory and add missing sections without replacing old content. Existing OS schedules need an explicit uninstall/reinstall to use the maintenance command; source updates alone do not rewrite them. Reminders remain local and never send messages.

If ffmpeg is not on PATH, pass `--ffmpeg C:/path/to/ffmpeg.exe` or set the `FFMPEG` / `FFPROBE`
environment variables.

---

## 2. Folder layout

```
ThinkNova_自动化工具包_v2/
  README.md              this file
  job.example.json       the job format shared by all publish scripts
  requirements.txt       Python packages
  .gitignore             keeps sessions / tokens / outputs out of git
  render/
    check.py             pre-publish check (spec, opening frames, loudness, silence, cuts, subtitles)
    loudnorm.py          two-pass loudness normalisation to -14 LUFS
    captions.py          transcribe -> SRT, burn SRT into video, SRT -> HyperFrames template
    hyperframes/
      vertical-slideshow/  9:16 template: title + image slideshow + one-line subtitles
  publish/
    common/              shared helpers (job loader, browser launcher)
    youtube/             official YouTube Data API: auth.py, upload.py, yt_captions.py
    tiktok/              browser automation: login.py, publish.py (+ tt_schedule.py)
    xiaohongshu/         browser automation: login.py, publish.py, dupcheck.py, reschedule.py
    douyin/              browser automation: login.py, publish.py, check.py
    facebook/            浏览器自动化（Meta Business Suite 发主页 Reels）：login.py, publish.py
    instagram/           浏览器自动化（Reels / 图片帖）：login.py, publish.py
    linkedin/            浏览器自动化（个人动态，纯文字）：login.py, publish.py
    x/                   浏览器自动化（文字 + 视频/图片）：login.py, publish.py
```

Typical flow: **make** (in your AI assistant with ThinkNova MCP) -> **render** (HyperFrames or
your editor) -> **loudnorm.py** -> **check.py** -> **publish/<platform>**.

---

## 3. job.json

One job file describes one video. The same file can be used for every platform: shared fields at
the top, per-platform overrides under `platforms.<name>` (`youtube`, `tiktok`, `xiaohongshu`,
`douyin`, `facebook`, `instagram`, `linkedin`, `x`). Relative paths are resolved from the folder that contains the job file. Keys that start
with `_` are comments. See `job.example.json`.

| Field | Type | Used by | Meaning |
|---|---|---|---|
| `video` | path | all（linkedin 忽略） | the finished mp4 |
| `images` | list of paths | xiaohongshu, instagram, x | image note; first image = cover。instagram：`format: carousel` 时用，1–10 张；x：没带视频时带前 4 张 |
| `cover` | path | tiktok | optional cover image (best effort) |
| `srt` | path | youtube | optional subtitle file, passed to check.py before upload |
| `title` | text | youtube, xiaohongshu, douyin | title (Xiaohongshu ~20 chars, Douyin 30 chars) |
| `caption` | text | all | post text; fallback for `description` / `body` / `desc` |
| `description` | text | youtube | description; `{{VIDEO_ID}}` is replaced after upload |
| `body` | list of text (or text) | xiaohongshu | paragraphs; one Enter between them |
| `desc` | text | douyin | description without hashtags |
| `tags` | list of text | all | tags / hashtags / topics, without `#` |
| `aigc` | true/false | all | declare AI-generated / altered content (default **true**)。Instagram 与 Facebook 不能确认「AI 标签」已开启即中止；X / LinkedIn 网页版没有该开关，只提示（需要声明请写进 caption） |
| `schedule` | `"YYYY-MM-DD HH:MM"` | all | scheduled time in this computer's local time; empty = publish now. TikTok: minutes in steps of 5, 20 min to 10 days ahead。facebook / linkedin / x：至少 15 分钟以后（facebook ≤29 天，linkedin ≤90 天）；**instagram 网页版不能定时，必须在 `platforms.instagram` 里写 `"schedule": ""`** |
| `privacy` | `private` / `unlisted` / `public` | youtube | default `private` |
| `publishAt` | RFC3339 UTC | youtube | e.g. `2026-11-01T11:00:00Z`; overrides `schedule` |
| `categoryId` | number | youtube | default 22 (People & Blogs) |
| `lang` | text | youtube | e.g. `en`, `zh-Hans` |
| `made_for_kids` | true/false | youtube | default false |
| `brand_disclosure` | true/false | tiktok | "Disclose post content -> Your brand" (default false) |
| `page_name` | text | facebook | 你的主页名；填了就核对 Business Suite 页面上显示的是这个主页，对不上就停（强烈建议填） |
| `composer_url` | URL | facebook | 起始页，默认 Business Suite 首页；管理多个主页时，粘贴已切到目标主页的 Business Suite 地址（须以 `https://business.facebook.com/` 开头） |
| `format` | `reel` / `carousel` | instagram | `reel` = 发 `video`（mp4/mov，默认）；`carousel` = 发 `images` |
| `attach_video` | true/false | x | 默认 true；false = 不带视频 |
| `max_chars` | number | x | 字数上限，默认 280（中日韩字符算 2、链接算 23）；付费账号可调大 |
| `type` | `video` / `image` | xiaohongshu | default: `video` if `video` is set |

---

## 4. Render

```bash
# loudness to -14 LUFS (video stream copied untouched)
python render/loudnorm.py in.mp4 out.mp4

# pre-publish check; exit code 2 = FAIL
python render/check.py out.mp4
python render/check.py out.mp4 --srt out.srt --max-dur 60 --sheet check_out
python render/check.py out.mp4 --speech --lang en          # also finds long gaps without speech

# subtitles
python render/captions.py transcribe out.mp4 out.srt --lang en
python render/captions.py burn out.mp4 out.srt out_subbed.mp4 --font "Noto Sans SC" --size 72
python render/captions.py tohtml out.srt render/hyperframes/vertical-slideshow/index.html
```

### HyperFrames (HTML -> video)

HyperFrames is an open-source command-line tool that renders an HTML page with a timeline into an
MP4. Nothing to install globally: `npx` downloads it on first use (Node 18+ required).

```bash
cd render/hyperframes/vertical-slideshow
npx hyperframes preview      # opens a preview in the browser; edit index.html and reload
npx hyperframes check        # lint + layout checks; fix every error before rendering
npx hyperframes render       # writes the MP4 into renders/
```

To start a fresh project instead of the template: `npx hyperframes init my-video`.

Template `vertical-slideshow` (1080x1920, 12 s):
1. Replace `assets/images/slide1.jpg ... slide3.jpg` with your images.
2. Edit the title in `index.html` (`#title`).
3. Subtitles: edit the `CAPTIONS` list, or run `captions.py tohtml your.srt index.html`.
4. Voice / music: put the file in `assets/audio/` and uncomment the `<audio>` line.
5. Font: put a font file at `assets/fonts/Main.ttf` (for Chinese, e.g. Noto Sans SC, free under
   the SIL Open Font License). Without it system fonts are used.
6. Keep `data-duration` on `#root` at least as long as the last slide, subtitle and audio.

Then run `loudnorm.py` and `check.py` on the rendered MP4.

---

## 5. Publish

All `--dry` commands perform local checks only; no login, upload or remote drafts. A mandatory upload rehearsal is not required. Use `--execute` only after explicit authorization.

```bash
# YouTube (official API)
python publish/youtube/auth.py                       # once
python publish/youtube/upload.py job.json --dry       # local checks only, no OAuth/upload
python publish/youtube/upload.py job.json --execute   # real upload, explicit confirmation required
python publish/youtube/yt_captions.py VIDEO_ID --get # download captions of your own video

# TikTok (browser automation)
python publish/tiktok/login.py                       # once
python publish/tiktok/publish.py job.json --dry
python publish/tiktok/publish.py job.json

# Xiaohongshu (browser automation)
python publish/xiaohongshu/login.py                  # once
python publish/xiaohongshu/publish.py job.json --dry
python publish/xiaohongshu/publish.py job.json
python publish/xiaohongshu/dupcheck.py               # list duplicate / similar titles (read only)
python publish/xiaohongshu/reschedule.py "Exact note title" "2026-11-05 20:00" --dry

# Douyin (browser automation)
python publish/douyin/login.py                       # once
python publish/douyin/publish.py job.json --dry
python publish/douyin/publish.py job.json
python publish/douyin/check.py                       # read-only list of your latest works

# Facebook / Instagram / LinkedIn / X（浏览器自动化；把 <平台> 换成 facebook / instagram / linkedin / x）
python publish/<平台>/login.py                       # 第一次：在弹出的窗口里自己登录
python publish/<平台>/publish.py --job job.json --dry       # 只填不发，停在最终按钮前
python publish/<平台>/publish.py --job job.json --execute   # 真发：必须显式写 --execute
```

这四个平台的 `publish.py` 不带 `--dry` / `--execute` 时只打印说明、什么都不做。没登录时会提示先跑 `login.py` 并以退出码 2 退出，不会填任何内容。

Exit codes: `0` ok, `1` bad input, `2` stopped by a check (nothing submitted, but see below),
`3` unexpected error, `4`/`5` (Xiaohongshu) duplicate found online after the run.

**An aborted run does not prove that nothing was posted.** Before re-running, look at the
platform's content list (or run `dupcheck.py` / `check.py`). TikTok and Xiaohongshu scripts check
for an existing post with the same caption / title before posting.

---

## 6. First login per platform

You always log in yourself, with your own account. The scripts never type passwords, never handle
captchas and never create accounts.

**YouTube** - uses your own Google Cloud OAuth client:
1. In Google Cloud Console create a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen (External; add your Google account as a test user).
3. Credentials -> Create credentials -> OAuth client ID -> **Desktop app** -> download the JSON.
4. Save it as `publish/youtube/oauth_client.json`.
5. Run `python publish/youtube/auth.py`, sign in with the account that owns the channel, click Allow.
   The token is saved as `publish/youtube/token.json`.
   While the consent screen is in **Testing** status, Google expires the authorisation after
   about 7 days; when uploads say "no usable authorisation", just run `auth.py` again.
   Every upload uses part of your Google Cloud project's daily API quota; uploads are the most
   expensive call, so see Google Cloud Console -> APIs & Services -> Quotas if uploads start failing.

**TikTok / Douyin** - run `login.py`; a separate browser window opens; log in (QR code is
quickest). The script detects the login by itself.

**Facebook / Instagram / LinkedIn / X** - 跑 `publish/<平台>/login.py`，在弹出的独立窗口里自己登录（含两步验证），脚本每 5 秒自动检查，登录成功即保存退出。Facebook 走 Meta Business Suite，登录的账号要有目标主页的发帖权限。

**Xiaohongshu** - run `login.py`, log in in the window, then press Enter in the terminal.
Use the same `--base` host for login and publishing (see `publish/xiaohongshu/xhs_urls.py`).

Login sessions are stored **only on this computer**, in `publish/<platform>/_profile/`
(or the folder you pass with `--profile`). That folder contains your session cookies and
storage: treat it like a password - do not share it, do not upload it, do not commit it.
Delete it to log out.

---

## 7. Risks - read before use

- **TikTok, Xiaohongshu, Douyin, Facebook, Instagram, LinkedIn and X scripts are browser automation.** They operate the platforms'
  web pages like a person would. When a platform changes its page, a script can stop working
  until it is updated.
- **Platform rules may not allow automated posting.** Using these scripts can lead to reduced
  reach, feature limits or account restrictions. You use them at your own risk and you are
  responsible for the consequences and for complying with each platform's terms.
- **YouTube uses the official YouTube Data API** with your own Google Cloud OAuth client and your
  own quota. It is the most stable path.
- Keep `_profile/`, `token.json` and `oauth_client.json` private. Never send them to anyone.
- AI-content labels: by default (`"aigc": true`) the scripts switch on each platform's
  AI-generated / altered-content declaration and abort if they cannot verify it. Whether and how
  to label your content is your decision and your responsibility under each platform's rules.
- Scheduled times are interpreted in the time zone of the computer / browser you run on.

---

## 中文说明

**这是什么**：把你用 ThinkNova MCP 在自己的 AI 助手（ChatGPT / Claude 等）里做出的图和视频，在你自己的电脑上渲染、检查、发布到各平台的脚本。工具包不生成内容、不审内容，只负责渲染、检查和发布。

**要装什么**：Python 3.10+、ffmpeg（含 ffprobe，放进 PATH）、Node.js 18+、Playwright（`pip install -r requirements.txt` 后再跑 `python -m playwright install chromium`）。`faster-whisper` 可选，只有要自动出字幕或查人声空档时才需要。

**目录**：`render/` 渲染与检查（成片检查 check.py、响度统一 loudnorm.py、字幕 captions.py、HyperFrames 竖版模板）；`publish/` 发布（youtube 官方接口、tiktok / xiaohongshu / douyin 浏览器自动化）；`job.example.json` 是所有发布脚本共用的任务格式。

**job.json**：一条视频一个文件。公共字段写在最外层，某个平台要不一样就写在 `platforms.<平台名>` 里覆盖。相对路径按 job 文件所在目录算。字段含义见第 3 节的表。

**常用命令**：见第 4、5 节。YouTube 的 `--dry` 仅本地检查，`--execute` 才实际上传，不再允许绕过检查。所有平台 `--dry` 只做本地检查，不上传、不创建草稿；真实上传/发布仍须对应确认。

**首次登录**：
- YouTube：用你自己的 Google Cloud 项目，开 YouTube Data API v3，建「桌面应用」OAuth 客户端，下载的 JSON 改名为 `oauth_client.json` 放进 `publish/youtube/`，再跑 `auth.py`，用拥有频道的 Google 账号点「允许」。同意屏幕处于「测试」状态时，授权大约 7 天过期，到时重跑一次 `auth.py` 即可。
- TikTok / 抖音：跑 `login.py`，在弹出的独立浏览器窗口里自己扫码登录，脚本自动识别登录成功。
- 小红书：跑 `login.py`，在窗口里自己登录后回终端按回车。
- Facebook / Instagram / LinkedIn / X：跑 `publish/<平台>/login.py`，在弹出的窗口里自己登录，脚本自动识别登录成功。发布命令是 `publish.py --job job.json --dry`（只填不发）和 `--execute`（真发，必须显式写）。
  - Facebook：通过 Meta Business Suite 给主页发 Reels，建议在 job 里填 `page_name` 防止发错主页。
  - Instagram：发 Reels 或图片帖；网页版不能定时，`schedule` 要留空。
  - LinkedIn：只发文字帖。
  - X：文字 + 1 个视频或最多 4 张图，默认 280 字上限（中日韩字符算 2）。
- 登录状态只存在你本机的 `publish/<平台>/_profile/` 目录里（含 cookie 等会话数据），等同密码：不要发给任何人、不要上传、不要提交到 git。删掉这个目录即退出登录。

**风险提示（使用前必读）**：
- TikTok、小红书、抖音、Facebook、Instagram、LinkedIn、X 脚本都是**浏览器自动化**，平台网页一改版，脚本可能失效。
- 平台规则**可能不允许自动化发布**，使用可能导致限流、功能受限或封号，**后果由使用者自行承担**，并自行遵守各平台规则。
- YouTube 走**官方接口**，需要你自己的 Google Cloud OAuth 客户端文件和配额，最稳定。
- 默认会打开各平台的「AI 生成内容」声明（`"aigc": true`），开不上就中止不发；是否声明、如何声明由你根据平台规则自行决定并负责。
- 脚本中止 ≠ 没发出去：重跑前先去平台后台（或用 `dupcheck.py` / `check.py`）确认一次。
- 定时时间按运行脚本那台电脑 / 浏览器的时区计算。
# AI 浏览器 / AI browser

AI 助手默认使用 ego lite；浏览器操作前运行 `ego-browser skill`。Windows x64 的 `bootstrap.py setup` 会在缺少时自动下载官方安装器，验证 Windows 签名并启动；用户仍需完成安装和首次引导，然后重新运行 setup。未完成时返回 `EGO_ONBOARDING_REQUIRED`，不会显示全就绪。已启动标记位于 `%LOCALAPPDATA%/ThinkNova/installers/ego-install-started`，安装失败检查后才删除该标记并重试。其他系统暂需从官网安装对应版本。

AI browser work defaults to ego lite. Windows x64 setup downloads and verifies the official installer; complete GUI installation/onboarding and rerun setup. Existing browser versions are not silently upgraded. Other platforms currently require the matching official installer. Legacy Python publishers still require Playwright Chromium; their profiles are preserved and are not automatically imported into ego lite.


## 分期可靠性升级 / Reliability upgrade

详见 AGENTS.md 与 AUTOMATION.md。拼片：`.venv` Python 执行 `render/assemble.py job.json --json`；显式 SRT 或估算字幕、静音作品、独立临时目录、禁止末帧补长。现有输出默认不覆盖。

普通发布：`publish/dispatch.py job.json --platform youtube --dry` 生成平台清单；明确确认后 `--execute --user-confirmed`。`--dry` 不上传/不产生草稿。浏览器脚本返回0但缺少可信回执时仍标为待核验，不能重复运行碰运气。

Readiness is capability-specific. Missing ego does not block API-only production. Mac without Homebrew receives the official https://brew.sh next action; system package managers are never silently installed. Existing customers approve updates, retain local data and reinstall schedules only after confirmation. Mac/unattended/browser-platform acceptance is tracked separately from local tests.
