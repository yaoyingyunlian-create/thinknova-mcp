# -*- coding: utf-8 -*-
"""X（原 Twitter）发帖：网页版浏览器自动化。

    python publish.py --job ../../job.example.json --dry       # 填到「发布」按钮前停下（一律先跑这个）
    python publish.py --job ../../job.example.json --execute   # 真的发布 / 定时

选项：
    --profile DIR    浏览器 profile 目录（默认 ./_profile，由 login.py 创建；两边要用同一个）
    --dry-wait SEC   --dry 填完后窗口保留几秒再关（默认 15）

用到的 job 字段（最外层，或写在 platforms.x 里覆盖）：
    caption       正文（必填）
    tags          话题，不带 #，自动拼成 #话题 接在正文后；不想带就在 platforms.x 写 "tags": []
    video         视频；attach_video 为 true（默认）时作为附件上传
    images        没有 video（或 attach_video=false）时，带前 4 张图
    attach_video  true/false，默认 true；false = 不带视频
    max_chars     字数上限，默认 280（按 X 的计法：中日韩字符算 2，链接算 23）；付费账号可调大
    schedule      "YYYY-MM-DD HH:MM"，按本机时区；空 = 立即发；至少 15 分钟以后
    aigc          X 网页版发帖界面没有 AI 标签开关：为 true 时只提示、不拦截；需要声明请写进 caption

规则（改脚本时请保留）：
  1. 只用 --dry 调试，不要拿真发流程试错。
  2. 关键控件必须「正好一个可见」才操作；找不到或找到多个就停，不猜。
  3. 正文填完必须原样读回，否则停。
  4. 中止 ≠ 没发出去：--execute 中途停了，先去 X 主页 / 定时列表看一眼再重跑。
登录从不自动化：先跑 login.py，自己登录。

风险：这是网页自动化，X 改版就可能失效；平台规则可能不允许自动化发布，后果由使用者自行承担。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import social  # noqa: E402
from common.browser import Abort, log  # noqa: E402

COMPOSE = "https://x.com/compose/post"
DLG = '[role="dialog"]'


def x_len(text):
    """X 的计数法：链接算 23；拉丁/常用标点算 1；中日韩等其它字符算 2。"""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    n = 0
    for ch in text:
        o = ord(ch)
        light = o <= 0x10FF or 0x2000 <= o <= 0x200D or 0x2010 <= o <= 0x201F or 0x2032 <= o <= 0x2037
        n += 1 if light else 2
    return n


def media_files(job):
    if job.get("attach_video", True) and job.get("video"):
        return [job["video"]]
    return list(job.get("images") or [])[:4]


def validate(job):
    if not (job.get("caption") or "").strip():
        raise Abort(u"缺少 caption")
    text = social.compose_text(job)
    lim = int(job.get("max_chars") or 280)
    if x_len(text) > lim:
        raise Abort(u"正文 %d 字（按 X 计法），超过上限 %d；缩短 caption，或在 platforms.x 里改 tags / max_chars"
                    % (x_len(text), lim))
    social.check_files(media_files(job))
    social.parse_schedule(job.get("schedule"))


def _select(el, values):
    for v in values:
        for kw in ("value", "label"):
            try:
                el.select_option(**{kw: v})
                return True
            except Exception:
                pass
    return False


def set_schedule(pg, dt):
    log(u"设置定时 %s ..." % dt.strftime("%Y-%m-%d %H:%M"))
    social.one_visible(pg.locator(DLG + ' [data-testid="scheduleOption"]'), u"X 定时按钮").click()
    pg.wait_for_timeout(1500)
    dlg = pg.locator(DLG).last
    d_in, t_in = social.visible(dlg.locator('input[type="date"]')), social.visible(dlg.locator('input[type="time"]'))
    if len(d_in) == 1 and len(t_in) == 1:
        d_in[0].fill(dt.strftime("%Y-%m-%d"))
        t_in[0].fill(dt.strftime("%H:%M"))
        got = "%s %s" % (d_in[0].input_value(), t_in[0].input_value())
        if social.ints(got) != social.ints(dt.strftime("%Y-%m-%d %H:%M")):
            raise Abort(u"定时回读不一致：%s" % got)
    else:
        def pick(rx, desc):
            return social.one_visible(dlg.get_by_label(re.compile(rx, re.I)), desc)
        ampm = social.visible(dlg.get_by_label(re.compile(r"^(AM/PM|上午/下午)$", re.I)))
        h = (dt.hour % 12 or 12) if ampm else dt.hour
        sels = [(pick(r"^(Month|月)$", u"定时「月」"), [str(dt.month), dt.strftime("%B")]),
                (pick(r"^(Day|日)$", u"定时「日」"), [str(dt.day)]),
                (pick(r"^(Year|年)$", u"定时「年」"), [str(dt.year)]),
                (pick(r"^(Hour|小时|时)$", u"定时「时」"), [str(h)]),
                (pick(r"^(Minute|分钟|分)$", u"定时「分」"), [str(dt.minute), "%02d" % dt.minute])]
        if len(ampm) == 1:
            sels.append((ampm[0], ["am", "AM", u"上午"] if dt.hour < 12 else ["pm", "PM", u"下午"]))
        for el, vals in sels:
            if not _select(el, vals):
                raise Abort(u"定时下拉框选不上 %s；页面可能改版，不发。" % vals[0])
        log(u"  定时下拉框已选")
    social.first_unique([
        dlg.locator('[data-testid="scheduledConfirmationPrimaryAction"]'),
        dlg.get_by_role("button", name=re.compile(r"^(Confirm|Update|确认|更新)$", re.I)),
    ], u"定时「Confirm」按钮").click()
    pg.wait_for_timeout(1500)
    note = social.visible(pg.get_by_text(re.compile(r"Will send on|将于", re.I)))
    log(u"  定时回读：%s" % (note[0].inner_text().strip() if note else u"没读到「Will send on」提示，请在截图里核对"))


def fill(pg, job, logs):
    social.ensure_logged_in(pg, "x", COMPOSE)
    text = social.compose_text(job)
    media = media_files(job)
    composer = social.wait_one_visible(pg, pg.locator(DLG + ' [data-testid="tweetTextarea_0"]'),
                                       u"X 发帖输入框", 25)
    log(u"填写正文（%d 字，按 X 计法）..." % x_len(text))
    composer.click()
    composer.fill(text)
    pg.wait_for_timeout(800)
    social.readback(text, composer.inner_text(), u"正文")

    if media:
        log(u"上传附件：%s ..." % ", ".join(os.path.basename(m) for m in media))
        fi = pg.locator(DLG + ' input[type="file"]')
        if fi.count() != 1:
            fi = pg.locator('input[type="file"][data-testid="fileInput"]')
        if fi.count() != 1:
            raise Abort(u"X 的附件上传口应为 1 个，实际 %d 个；不猜，停止。" % fi.count())
        fi.set_input_files(media)
        try:
            pg.locator(DLG + ' video, ' + DLG + ' img[src^="blob:"], ' + DLG + ' [data-testid="attachments"]') \
              .first.wait_for(state="visible", timeout=120000)
        except Exception:
            raise Abort(u"2 分钟内没看到附件预览；不发。")
        log(u"  附件预览已出现")

    if job.get("aigc", True):
        log(u"  提示：X 网页版没有 AI 标签开关；需要声明 AI 生成，请写进 caption。")

    dt = social.parse_schedule(job.get("schedule"))
    if dt:
        set_schedule(pg, dt)

    final = pg.locator(DLG + ' [data-testid="tweetButton"]')
    log(u"  最终按钮（%s）：找到 %d 个，未点击" % ("Schedule" if dt else "Post", len(social.visible(final))))

    def submit():
        btn = social.one_visible(final, u"X 最终发布按钮")
        for _ in range(150):   # 视频还在处理时按钮是灰的，最多等 5 分钟
            if btn.is_enabled() and btn.get_attribute("aria-disabled") != "true":
                break
            pg.wait_for_timeout(2000)
        else:
            raise Abort(u"发布按钮 5 分钟内一直不可点（视频可能还在处理）；没有提交。")
        btn.click()
        log(u"  已点击最终按钮")
        for _ in range(30):
            pg.wait_for_timeout(1000)
            if not social.visible(pg.locator(DLG + ' [data-testid="tweetTextarea_0"]')):
                log(u"已提交：发帖框已关闭。请到 X 主页%s确认一次。"
                    % (u"（定时帖在 发帖框 → Drafts → Scheduled）" if dt else ""))
                return
        raise Abort(u"点了发布但发帖框 30 秒没关闭；可能失败也可能已发出，先去 X 主页确认再重跑。")
    return submit


if __name__ == "__main__":
    sys.exit(social.run_publish("x", HERE, __doc__, validate, fill))
