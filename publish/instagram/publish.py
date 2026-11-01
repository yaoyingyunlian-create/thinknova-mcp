# -*- coding: utf-8 -*-
"""Instagram 发帖（Reels 视频 / 图片帖）：网页版浏览器自动化。

    python publish.py --job ../../job.example.json --dry       # 填到「Share」按钮前停下（一律先跑这个）
    python publish.py --job ../../job.example.json --execute   # 真的发布

选项：
    --profile DIR    浏览器 profile 目录（默认 ./_profile，由 login.py 创建；两边要用同一个）
    --dry-wait SEC   --dry 填完后窗口保留几秒再关（默认 15）

用到的 job 字段（最外层，或写在 platforms.instagram 里覆盖）：
    format     "reel"（默认，有 video 时）= 发 video；"carousel" = 发 images（1–10 张，1 张即单图帖）
    video      Reels 视频，mp4 / mov
    images     图片帖用
    caption    正文（必填，最多 2200 字）
    tags       话题，不带 #，自动拼成 #话题 接在正文后（最多 30 个）
    aigc       true（默认）= 打开「AI 标签」（Add AI label）并回读，开不上就中止不发；
               确定不需要声明时在 platforms.instagram 写 "aigc": false
    schedule   Instagram 网页版没有定时发布：这里必须为空（在 platforms.instagram 写 "schedule": ""），
               要定时请用手机 App 或 Meta Business Suite

规则（改脚本时请保留）：
  1. 只用 --dry 调试，不要拿真发流程试错。
  2. 关键控件必须「正好一个可见」才操作；找不到或找到多个就停，不猜。
  3. 正文填完必须原样读回，否则停；流程中只点「Next」，「Share」只在 --execute 时点一次。
  4. 中止 ≠ 没发出去：--execute 中途停了，先去自己的主页看一眼再重跑。
登录从不自动化：先跑 login.py，自己登录。

风险：这是网页自动化，Instagram 改版就可能失效；平台规则可能不允许自动化发布，后果由使用者自行承担。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import social  # noqa: E402
from common.browser import Abort, log  # noqa: E402

HOME = "https://www.instagram.com/"
DLG = '[role="dialog"]'
CAPTION = DLG + ' [contenteditable="true"][role="textbox"], ' + DLG + ' textarea'
AI_NAME = re.compile(u"AI label|AI-generated|AI 标签|AI 信息|人工智能标签", re.I)
AI_LABEL = re.compile(u"^(Add AI label|AI label|添加 ?AI ?标签|AI ?标签)$", re.I)


def plan(job):
    fmt = (job.get("format") or ("reel" if job.get("video") else "carousel")).lower()
    if fmt == "reel":
        v = job.get("video")
        if not v:
            raise Abort(u"format=reel 需要 video")
        if not re.search(r"\.(mp4|mov)$", v, re.I):
            raise Abort(u"Reels 视频必须是 mp4 或 mov：%s" % v)
        return fmt, [v]
    if fmt == "carousel":
        imgs = list(job.get("images") or [])
        if not 1 <= len(imgs) <= 10:
            raise Abort(u"图片帖需要 1–10 张 images，实际 %d 张" % len(imgs))
        return fmt, imgs
    raise Abort(u"format 只能是 reel 或 carousel，实际是 %r" % fmt)


def validate(job):
    if not (job.get("caption") or "").strip():
        raise Abort(u"缺少 caption")
    if (job.get("schedule") or "").strip():
        raise Abort(u"Instagram 网页版不支持定时发布。请在 platforms.instagram 里写 \"schedule\": \"\"（立即发），"
                    u"要定时请用手机 App 或 Meta Business Suite。")
    text = social.compose_text(job)
    if len(text) > 2200:
        raise Abort(u"正文 %d 字，超过 Instagram 上限 2200" % len(text))
    if len(social.hashtags(job.get("tags"))) > 30:
        raise Abort(u"话题超过 30 个")
    social.check_files(plan(job)[1])


def fill(pg, job, logs):
    social.ensure_logged_in(pg, "instagram", HOME)
    fmt, files = plan(job)
    text = social.compose_text(job)
    rx_new = re.compile(u"^(New post|Create|新帖子|创建)$", re.I)
    social.first_unique([
        pg.locator('svg[aria-label="New post"]'),
        pg.locator(u'svg[aria-label="新帖子"]'),
        pg.locator(u'svg[aria-label="创建"]'),
        pg.get_by_role("link", name=rx_new),
        pg.get_by_role("button", name=rx_new),
    ], u"Instagram「Create / 新帖子」入口").click()
    pg.wait_for_timeout(1500)
    # 新版界面点 Create 后会先弹一个小菜单（Post / Live / Ad），选 Post
    for role in ("link", "menuitem", "button"):
        sub = social.visible(pg.get_by_role(role, name=re.compile(u"^(Post|帖子|贴文)$", re.I)))
        if len(sub) == 1:
            sub[0].click()
            pg.wait_for_timeout(1500)
            break

    fi = pg.locator(DLG + ' input[type="file"]')
    for _ in range(40):
        if fi.count():
            break
        pg.wait_for_timeout(500)
    if fi.count() != 1:
        raise Abort(u"Instagram 的选择文件口应为 1 个，实际 %d 个；不猜，停止。" % fi.count())
    log(u"选择文件（%s）：%s ..." % (fmt, ", ".join(os.path.basename(f) for f in files)))
    fi.set_input_files(files)
    pg.wait_for_timeout(2500)
    ok = social.visible(pg.get_by_role("button", name=re.compile(u"^(OK|确定|好)$", re.I)))
    if len(ok) == 1:          # 「视频帖现在会以 Reels 形式分享」提示
        ok[0].click()
        pg.wait_for_timeout(800)

    # 裁剪 → 编辑 → 写说明：只点 Next，直到出现说明输入框
    caption, clicks = None, 0
    for _ in range(45):
        cap = social.visible(pg.locator(CAPTION))
        if len(cap) == 1:
            caption = cap[0]
            break
        nxt = social.visible(pg.locator(DLG).get_by_role("button", name=re.compile(u"^(Next|下一步|继续)$", re.I)))
        if nxt and clicks < 3:
            nxt[-1].click()
            clicks += 1
            pg.wait_for_timeout(2500)
        else:
            pg.wait_for_timeout(2000)
    if caption is None:
        raise Abort(u"没走到写说明那一步（找不到唯一的说明输入框）；不发。")
    if fmt == "reel" and re.search(u"New reel|新 ?Reels?", pg.inner_text("body"), re.I):
        log(u"  界面确认：Reels 编辑器")

    log(u"填写正文（%d 字）..." % len(text))
    caption.click()
    caption.fill(text)
    pg.wait_for_timeout(800)
    social.readback(text, social.read_text(caption), u"正文")

    if job.get("aigc", True):
        st = social.ensure_toggle_on(pg, AI_NAME, AI_LABEL, u"AI 标签")
        if st is None:
            adv = social.visible(pg.get_by_role("button", name=re.compile(u"^(Advanced settings|高级设置)$", re.I)))
            if not adv:
                adv = social.visible(pg.get_by_text(re.compile(u"^(Advanced settings|高级设置)$", re.I)))
            if len(adv) == 1:
                adv[0].click()
                pg.wait_for_timeout(1200)
                st = social.ensure_toggle_on(pg, AI_NAME, AI_LABEL, u"AI 标签")
        if st is not True:
            raise Abort(u"aigc=true，但没能确认「AI 标签」已打开；不发。若确定不需要声明，"
                        u"在 platforms.instagram 写 \"aigc\": false。")

    final = pg.locator(DLG).get_by_role("button", name=re.compile(u"^(Share|分享|发布)$", re.I))
    log(u"  最终按钮（Share）：找到 %d 个，未点击" % len(social.visible(final)))

    def submit():
        social.one_visible(final, u"Instagram「Share」按钮").click()
        log(u"  已点击 Share，等待完成（最多 5 分钟）...")
        try:
            pg.get_by_text(re.compile(u"has been shared|been shared|已分享|已发布|分享成功", re.I)) \
              .first.wait_for(state="visible", timeout=300000)
        except Exception:
            raise Abort(u"5 分钟内没看到「已分享」提示；可能失败也可能已发出，先去主页确认再重跑。")
        log(u"已发布。请到自己的主页确认一次。")
    return submit


if __name__ == "__main__":
    sys.exit(social.run_publish("instagram", HERE, __doc__, validate, fill))
