# -*- coding: utf-8 -*-
"""Facebook 主页发 Reels 视频：通过 Meta Business Suite 网页版浏览器自动化。

    python publish.py --job ../../job.example.json --dry       # 填到最终「Share / Schedule」按钮前停下（一律先跑这个）
    python publish.py --job ../../job.example.json --execute   # 真的发布 / 定时

选项：
    --profile DIR    浏览器 profile 目录（默认 ./_profile，由 login.py 创建；两边要用同一个）
    --dry-wait SEC   --dry 填完后窗口保留几秒再关（默认 15）

用到的 job 字段（最外层，或写在 platforms.facebook 里覆盖）：
    video          Reels 视频，mp4 / mov（必填）
    caption        正文（必填）
    tags           话题，不带 #，自动拼成 #话题 接在正文后
    page_name      你的主页名（可选，强烈建议填）：填了就核对 Business Suite 页面上确实显示这个名字，
                   对不上就停 —— 防止发到别的主页
    composer_url   起始页（可选）：默认 Business Suite 首页；你管理多个主页时，可以把浏览器地址栏里
                   已切到目标主页的 Business Suite 地址粘到这里（必须是 business.facebook.com 开头）
    aigc           true（默认）= 必须打开并回读「AI 标签 / AI info」；找不到或无法确认时中止，不发布。
    schedule       "YYYY-MM-DD HH:MM"，按本机时区；空 = 立即发；至少 15 分钟以后、29 天以内

规则（改脚本时请保留）：
  1. 只用 --dry 调试，不要拿真发流程试错。
  2. 关键控件必须「正好一个可见」才操作；找不到或找到多个就停，不猜。
  3. 正文、文件名、定时时间都要回读一致，否则停；流程中只点「Next」，最终按钮只在 --execute 时点一次。
  4. 中止 ≠ 没发出去：--execute 中途停了，先去 Business Suite → 内容 / 日历看一眼再重跑。
登录从不自动化：先跑 login.py，自己登录。

风险：这是网页自动化，Meta 改版就可能失效；平台规则可能不允许自动化发布，后果由使用者自行承担。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import social  # noqa: E402
from common.browser import Abort, log  # noqa: E402

HOME = "https://business.facebook.com/latest/home"
TEXTBOX = 'textarea, [contenteditable="true"][role="textbox"]'
SHARE_STAGE = re.compile(u"Scheduling options|Share now|Share to|发布时间设置|发定时帖|立即分享", re.I)
AI_NAME = re.compile(u"AI info|AI information|AI-generated|AI label|AI 信息|AI 标签|人工智能标签", re.I)
AI_LABEL = re.compile(u"^(AI info|Add AI label|AI label|AI 信息|添加 ?AI ?标签)$", re.I)


def validate(job):
    if not (job.get("caption") or "").strip():
        raise Abort(u"缺少 caption")
    v = job.get("video")
    if not v:
        raise Abort(u"Facebook Reels 需要 video")
    if not re.search(r"\.(mp4|mov)$", v, re.I):
        raise Abort(u"Reels 视频必须是 mp4 或 mov：%s" % v)
    social.check_files([v])
    url = (job.get("composer_url") or "").strip()
    if url and not url.startswith("https://business.facebook.com/"):
        raise Abort(u"composer_url 必须以 https://business.facebook.com/ 开头")
    social.parse_schedule(job.get("schedule"), max_days=29)


def spin_to(pg, el, target, mod=None):
    """把 ARIA spinbutton 用方向键调到目标值。"""
    for _ in range(80):
        cur = el.get_attribute("aria-valuenow")
        try:
            cur = int(float(cur))
        except Exception:
            raise Abort(u"时间框没有数值（aria-valuenow），页面可能改版；不发。")
        if cur == target:
            return
        if mod:   # 分钟只往上加、跨 60 回绕，避免中途选到过去的时间
            el.press("ArrowUp")
        else:
            el.press("ArrowUp" if target > cur else "ArrowDown")
        pg.wait_for_timeout(60)
    raise Abort(u"时间框调不到 %d；不发。" % target)


def set_schedule(pg, dt):
    log(u"设置定时 %s ..." % dt.strftime("%Y-%m-%d %H:%M"))
    social.first_unique([
        pg.get_by_role("radio", name=re.compile(u"^(Schedule|安排时间|定时)", re.I)),
        pg.get_by_role("button", name=re.compile(u"^(Schedule|安排|定时)", re.I)),
    ], u"「Schedule / 定时」选项").click()
    pg.wait_for_timeout(1500)
    date = social.first_unique([
        pg.locator(u'input[placeholder="年-月-日"]'),
        pg.locator('input[placeholder^="yyyy" i]'),
        pg.locator('input[placeholder^="mm/dd" i]'),
        pg.locator('input[placeholder^="dd/mm" i]'),
    ], u"定时日期框")
    ph = (date.get_attribute("placeholder") or "").lower()
    if ph.startswith("mm"):
        dtxt, want_d = dt.strftime("%m/%d/%Y"), [dt.month, dt.day, dt.year]
    elif ph.startswith("dd"):
        dtxt, want_d = dt.strftime("%d/%m/%Y"), [dt.day, dt.month, dt.year]
    else:
        dtxt, want_d = dt.strftime("%Y-%m-%d"), [dt.year, dt.month, dt.day]
    sb = 'input[role="spinbutton"]'
    hour = social.first_unique([pg.locator(sb + u'[aria-label="小时"]'), pg.locator(sb + '[aria-label="hours" i]'),
                                pg.locator(sb + '[aria-label="hour" i]')], u"定时「小时」框")
    minute = social.first_unique([pg.locator(sb + u'[aria-label="分钟"]'), pg.locator(sb + '[aria-label="minutes" i]'),
                                  pg.locator(sb + '[aria-label="minute" i]')], u"定时「分钟」框")
    mer = social.visible(pg.locator(sb + '[aria-label="meridiem" i], ' + sb + '[aria-label*="AM/PM" i], '
                                    + sb + u'[aria-label*="上午"]'))
    spin_to(pg, minute, dt.minute, mod=60)
    spin_to(pg, hour, (dt.hour % 12 or 12) if len(mer) == 1 else dt.hour)
    if len(mer) == 1:
        want = "AM" if dt.hour < 12 else "PM"
        for _ in range(2):
            if (mer[0].get_attribute("aria-valuetext") or mer[0].input_value() or "").upper().startswith(want):
                break
            mer[0].press("ArrowUp")
            pg.wait_for_timeout(200)
    if social.ints(date.input_value()) != want_d:
        date.click()
        pg.keyboard.press("Control+A")
        pg.keyboard.type(dtxt, delay=30)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(800)
    got = (date.input_value(), hour.get_attribute("aria-valuenow"), minute.get_attribute("aria-valuenow"))
    want_h = (dt.hour % 12 or 12) if len(mer) == 1 else dt.hour
    if social.ints(got[0]) != want_d or social.ints(got[1])[:1] != [want_h] or social.ints(got[2])[:1] != [dt.minute]:
        raise Abort(u"定时回读不一致：日期=%s 时=%s 分=%s（想要 %s）；不发。"
                    % (got[0], got[1], got[2], dt.strftime("%Y-%m-%d %H:%M")))
    log(u"  定时回读：%s %s:%s" % got)


def final_buttons(pg, scheduled):
    rx = u"^(Schedule|发定时帖|安排发布|定时发布)$" if scheduled else u"^(Share now|Share|Publish|立即分享|分享|发布)$"
    return [b for b in social.visible(pg.get_by_role("button", name=re.compile(rx, re.I)))
            if b.get_attribute("aria-pressed") != "true"]


def fill(pg, job, logs):
    start = (job.get("composer_url") or "").strip() or HOME
    social.ensure_logged_in(pg, "facebook", start)
    pg.wait_for_timeout(3000)
    page_name = (job.get("page_name") or "").strip()
    if page_name:
        if page_name not in pg.inner_text("body"):
            raise Abort(u"页面上没看到主页名「%s」：Business Suite 当前选中的可能不是这个主页。"
                        u"先在 Business Suite 左上角切到正确的主页（或填 composer_url）再跑。" % page_name)
        log(u"  主页名核对通过：%s" % page_name)
    else:
        log(u"  提示：没填 page_name，不核对主页名；请在 --dry 截图里确认发到的是哪个主页。")

    video = job["video"]
    if "reels_composer" not in pg.url:
        social.first_unique([
            pg.get_by_role("button", name=re.compile(u"create reels?|创建短片|创建 ?reels?", re.I)),
            pg.get_by_role("link", name=re.compile(u"create reels?|创建短片|创建 ?reels?", re.I)),
        ], u"Business Suite「Create reel」入口").click()
        try:
            pg.wait_for_url(re.compile("reels_composer"), timeout=20000)
        except Exception:
            pass
    log(u"选择视频：%s ..." % os.path.basename(video))
    fi = pg.locator('input[type="file"]')
    if fi.count() > 1:
        raise Abort(u"页面上有 %d 个选择文件口；不猜，停止。" % fi.count())
    if fi.count() == 1:
        fi.set_input_files(video)
    else:
        add = social.wait_one_visible(pg, pg.get_by_role("button", name=re.compile(u"add video|添加视频", re.I)),
                                      u"「Add video」按钮", 20)
        with pg.expect_file_chooser(timeout=15000) as fc:
            add.click()
        fc.value.set_files(video)
    log(u"  等待上传完成（最多 5 分钟）...")
    try:
        pg.wait_for_function("() => /100\\s*%|upload complete|上传完成/i.test(document.body.innerText)",
                             timeout=300000)
    except Exception:
        raise Abort(u"5 分钟内没看到上传完成；不发。")
    if os.path.basename(video) not in pg.inner_text("body"):
        raise Abort(u"页面上没读到所选文件名 %s；不发。" % os.path.basename(video))
    log(u"  上传完成，文件名回读一致")

    text = social.compose_text(job)
    body = pg.inner_text("body")
    if not SHARE_STAGE.search(body):
        box = social.one_visible(pg.locator(TEXTBOX), u"Reels 说明输入框")
        log(u"填写正文（%d 字）..." % len(text))
        box.click()
        box.fill(text)
        pg.wait_for_timeout(800)
        social.readback(text, social.read_text(box), u"正文")
        for _ in range(3):      # 只点 Next，走到「分享 / 定时」那一步
            nxt = social.visible(pg.get_by_role("button", name=re.compile(u"^(Next|下一页|下一步)$", re.I)))
            if not nxt:
                break
            nxt[-1].click()
            pg.wait_for_timeout(1500)
            if SHARE_STAGE.search(pg.inner_text("body")):
                break
    elif text.strip() not in body:
        raise Abort(u"编辑器已经停在分享那一步，但页面上没有这条正文；为免覆盖别的草稿，停止。")
    if not SHARE_STAGE.search(pg.inner_text("body")):
        raise Abort(u"没走到「分享 / 定时」那一步；不发。")

    if job.get("aigc", True):
        st = social.ensure_toggle_on(pg, AI_NAME, AI_LABEL, u"AI 标签")
        if st is not True:
            raise Abort(u"aigc=true，但没能确认 Facebook 的 AI 标签已打开；不发布。")

    dt = social.parse_schedule(job.get("schedule"), max_days=29)
    if dt:
        set_schedule(pg, dt)
    log(u"  最终按钮（%s）：找到 %d 个，未点击" % ("Schedule" if dt else "Share", len(final_buttons(pg, dt))))

    def submit():
        b = final_buttons(pg, dt)
        if len(b) != 1:
            raise Abort(u"最终按钮应为 1 个，实际 %d 个；不猜，没有提交。" % len(b))
        b[0].click()
        log(u"  已点击最终按钮，等待完成（最多 3 分钟）...")
        try:
            pg.wait_for_function(
                "() => /(has been|was) (shared|scheduled|published)|reel (shared|scheduled)|已发布|已安排|已分享|已排期/i"
                ".test(document.body.innerText) || !location.pathname.includes('reels_composer')",
                timeout=180000)
        except Exception:
            raise Abort(u"3 分钟内没看到完成提示；可能失败也可能已发出，先去 Business Suite → 内容 / 日历确认再重跑。")
        log(u"已提交。请到 Business Suite → 内容%s确认一次。" % (u" / 日历" if dt else ""))
    return submit


if __name__ == "__main__":
    sys.exit(social.run_publish("facebook", HERE, __doc__, validate, fill))
