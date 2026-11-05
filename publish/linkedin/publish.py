# -*- coding: utf-8 -*-
"""LinkedIn 发帖（个人主页动态，纯文字）：网页版浏览器自动化。

    python publish.py --job ../../job.example.json --dry       # 仅本地检查，不上传
    python publish.py --job ../../job.example.json --execute   # 真的发布 / 定时

选项：
    --profile DIR    浏览器 profile 目录（默认 ./_profile，由 login.py 创建；两边要用同一个）
    --dry-wait SEC   --dry 填完后窗口保留几秒再关（默认 15）

用到的 job 字段（最外层，或写在 platforms.linkedin 里覆盖）：
    caption    正文（必填，最多 3000 字）；LinkedIn 适合写得比短视频文案长一些，可以单独覆盖
    tags       话题，不带 #，自动拼成 #话题 接在正文后
    schedule   "YYYY-MM-DD HH:MM"，按本机时区；空 = 立即发；至少 15 分钟以后
    video / images / aigc   本脚本只发文字帖，这几项会被忽略（要带视频请在网页上手动加）

规则（改脚本时请保留）：
  1. 只用 --dry 调试，不要拿真发流程试错。
  2. 关键控件必须「正好一个可见」才操作；找不到或找到多个就停，不猜。
  3. 正文填完必须原样读回，否则停。
  4. 中止 ≠ 没发出去：--execute 中途停了，先去 LinkedIn 主页 / 定时列表看一眼再重跑。
登录从不自动化：先跑 login.py，自己登录。

风险：这是网页自动化，LinkedIn 改版就可能失效；平台规则可能不允许自动化发布，后果由使用者自行承担。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import social  # noqa: E402
from common.browser import Abort, log  # noqa: E402

FEED = "https://www.linkedin.com/feed/"
DLG = '[role="dialog"]'
EDITOR = (DLG + ' [role="textbox"][contenteditable="true"], '
          + DLG + ' .ql-editor[contenteditable="true"]')


def validate(job):
    if not (job.get("caption") or "").strip():
        raise Abort(u"缺少 caption")
    text = social.compose_text(job)
    if len(text) > 3000:
        raise Abort(u"正文 %d 字，超过 LinkedIn 上限 3000" % len(text))
    social.parse_schedule(job.get("schedule"), max_days=90)


def set_schedule(pg, dt):
    log(u"设置定时 %s ..." % dt.strftime("%Y-%m-%d %H:%M"))
    social.first_unique([
        pg.get_by_role("button", name=re.compile(r"schedule post|^schedule$", re.I)),
        pg.get_by_role("button", name=re.compile(u"安排|定时", re.I)),
    ], u"LinkedIn 定时（时钟）按钮").click()
    pg.wait_for_timeout(1500)
    dlg = pg.locator(DLG).last
    d_in, t_in = social.visible(dlg.locator('input[type="date"]')), social.visible(dlg.locator('input[type="time"]'))
    h12 = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
    if len(d_in) == 1 and len(t_in) == 1:
        d_el, t_el = d_in[0], t_in[0]
        d_el.fill(dt.strftime("%Y-%m-%d"))
        t_el.fill(dt.strftime("%H:%M"))
        want_d, want_t = [dt.year, dt.month, dt.day], [dt.hour, dt.minute]
    else:
        d_el = social.one_visible(dlg.get_by_label(re.compile(u"^\\s*(Date|日期)", re.I)), u"定时日期框")
        t_el = social.one_visible(dlg.get_by_label(re.compile(u"^\\s*(Time|时间)", re.I)), u"定时时间框")
        d_el.fill(dt.strftime("%m/%d/%Y"))
        d_el.press("Enter")
        t_el.fill(h12)
        t_el.press("Enter")
        want_d, want_t = [dt.month, dt.day, dt.year], [dt.hour % 12 or 12, dt.minute]
    pg.wait_for_timeout(800)
    got_d, got_t = social.read_text(d_el), social.read_text(t_el)
    if social.ints(got_d) != want_d or social.ints(got_t)[:2] != want_t:
        raise Abort(u"定时回读不一致：日期=%s 时间=%s（想要 %s）；不发。" % (got_d, got_t, h12))
    log(u"  定时回读：%s %s" % (got_d, got_t))
    social.one_visible(dlg.get_by_role("button", name=re.compile(u"^(Next|下一步)$", re.I)),
                       u"定时「Next」按钮").click()
    pg.wait_for_timeout(1500)


def fill(pg, job, logs):
    social.ensure_logged_in(pg, "linkedin", FEED)
    if job.get("video") or job.get("images"):
        log(u"  提示：LinkedIn 脚本只发文字帖，video / images 已忽略。")
    text = social.compose_text(job)
    social.first_unique([
        pg.get_by_role("button", name=re.compile(u"^\\s*(Start a post|开始发帖|发动态|发帖)", re.I)),
        pg.locator("button.share-box-feed-entry__trigger"),
    ], u"LinkedIn「Start a post」入口").click()
    editor = social.wait_one_visible(pg, pg.locator(EDITOR), u"LinkedIn 发帖编辑框", 20)
    log(u"填写正文（%d 字）..." % len(text))
    editor.click()
    editor.fill(text)
    pg.wait_for_timeout(800)
    social.readback(text, editor.inner_text(), u"正文")

    dt = social.parse_schedule(job.get("schedule"), max_days=90)
    if dt:
        set_schedule(pg, dt)
        social.readback(text, social.one_visible(pg.locator(EDITOR), u"LinkedIn 发帖编辑框").inner_text(),
                        u"定时后正文")

    rx = u"^\\s*(Schedule|安排|定时发布)\\s*$" if dt else u"^\\s*(Post|发布|发帖)\\s*$"
    final = pg.locator(DLG).get_by_role("button", name=re.compile(rx, re.I))
    log(u"  最终按钮（%s）：找到 %d 个，未点击" % ("Schedule" if dt else "Post", len(social.visible(final))))

    def submit():
        btn = social.one_visible(final, u"LinkedIn 最终发布按钮")
        if not btn.is_enabled():
            raise Abort(u"最终按钮是灰的，不可点；没有提交。")
        btn.click()
        log(u"  已点击最终按钮")
        for _ in range(30):
            pg.wait_for_timeout(1000)
            if not social.visible(pg.locator(EDITOR)):
                log(u"已提交：发帖框已关闭。请到 LinkedIn 主页%s确认一次。"
                    % (u"（定时帖在 Start a post → 时钟图标 → View all scheduled posts）" if dt else ""))
                return
        raise Abort(u"点了发布但发帖框 30 秒没关闭；可能失败也可能已发出，先去 LinkedIn 主页确认再重跑。")
    return submit


if __name__ == "__main__":
    sys.exit(social.run_publish("linkedin", HERE, __doc__, validate, fill))
