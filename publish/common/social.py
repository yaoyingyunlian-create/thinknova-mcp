# -*- coding: utf-8 -*-
"""海外四个平台（Facebook / Instagram / LinkedIn / X）浏览器发布脚本的共用逻辑。

做什么：
  * 每个平台用自己的持久化浏览器 profile（默认 publish/<平台>/_profile），
    复用你在 login.py 打开的窗口里手动登录后的状态；
  * 判断「是否已登录」：没登录就给出中文提示并退出（退出码 2），什么都不填、什么都不发；
  * 统一的命令行：
        python publish.py --job job.json --dry       只填到最后一步前停下（先跑这个）
        python publish.py --job job.json --execute   真的发布（必须显式写 --execute）
  * 小工具：只认「正好一个可见」的控件、开关回读、正文回读、定时时间解析、#话题拼接。

不做什么：不输入账号密码、不处理验证码、不创建账号。登录一律由你自己完成。
"""
import datetime
import os
import re
import sys
import time

from . import jobfile, browser
from .browser import Abort, log


class NotLoggedIn(Abort):
    """当前浏览器 profile 没有登录这个平台。"""


# login_url：网址里出现这些片段 = 在登录 / 验证页
# login_text：页面上出现这些文字 = 在登录页
# ok_sel / ok_url：看到这些 = 已登录
SITES = {
    "x": dict(
        name="X",
        home="https://x.com/home",
        login_url=("/login", "/i/flow/", "/onboarding", "/logout", "/account/access"),
        login_text=("Sign in to X", "Happening now", "Join today", u"登录 X"),
        ok_sel='[data-testid="SideNav_NewTweet_Button"], [data-testid="AppTabBar_Home_Link"], '
               '[data-testid="tweetTextarea_0"]',
        ok_url=(),
    ),
    "linkedin": dict(
        name="LinkedIn",
        home="https://www.linkedin.com/feed/",
        login_url=("/login", "/uas/", "/authwall", "/checkpoint", "/signup", "/start/join"),
        login_text=("Sign in to LinkedIn", "Join LinkedIn", "Welcome to your professional community",
                    u"登录领英"),
        ok_sel='#global-nav, .global-nav, [data-test-global-nav]',
        ok_url=(),
    ),
    "instagram": dict(
        name="Instagram",
        home="https://www.instagram.com/",
        login_url=("/accounts/login", "/challenge", "/accounts/suspended", "/accounts/emailsignup"),
        login_text=("Log in with Facebook", "Don't have an account?", "Forgot password?",
                    u"使用 Facebook 登录", u"忘记密码"),
        ok_sel='svg[aria-label="Home"], svg[aria-label="New post"], svg[aria-label="Search"], '
               u'svg[aria-label="首页"], svg[aria-label="主页"], svg[aria-label="新帖子"], '
               'a[href="/direct/inbox/"]',
        ok_url=(),
    ),
    "facebook": dict(
        name=u"Facebook（Meta Business Suite）",
        home="https://business.facebook.com/latest/home",
        login_url=("/login", "loginpage", "/checkpoint", "two_factor", "two_step_verification",
                   "/recover"),
        login_text=("Log in to Facebook", "Log into Facebook", "Log in with Facebook", "Log in to Business Tools",
                    u"登录 Facebook", u"使用 Facebook 登录"),
        ok_sel=None,
        ok_url=("business.facebook.com/latest",),
    ),
}


# ---------------------------------------------------------------- 控件小工具
def visible(locator):
    """返回 locator 里所有可见的元素（列表）。出错时返回空列表。"""
    out = []
    try:
        n = locator.count()
    except Exception:
        return out
    for i in range(n):
        el = locator.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except Exception:
            pass
    return out


def one_visible(locator, desc):
    """正好一个可见才返回；0 个或多个都停下，不猜。"""
    v = visible(locator)
    if len(v) != 1:
        raise Abort(u"%s：应正好找到 1 个可见控件，实际 %d 个；不猜，停止。" % (desc, len(v)))
    return v[0]


def wait_one_visible(pg, locator, desc, seconds=20):
    """最多等 seconds 秒，直到正好一个可见。"""
    end = time.time() + seconds
    while True:
        v = visible(locator)
        if len(v) == 1:
            return v[0]
        if time.time() > end:
            raise Abort(u"%s：%d 秒内没等到唯一的可见控件（实际 %d 个），页面可能改版了；停止。"
                        % (desc, seconds, len(v)))
        pg.wait_for_timeout(500)


def first_unique(candidates, desc):
    """依次试几种定位方式，取第一个「正好一个可见」的。"""
    seen = []
    for loc in candidates:
        v = visible(loc)
        if len(v) == 1:
            return v[0]
        seen.append(len(v))
    raise Abort(u"%s：没找到唯一的可见控件（各定位方式命中 %s 个），页面可能改版了；停止。"
                % (desc, "/".join(map(str, seen))))


def read_text(el):
    try:
        return el.input_value()
    except Exception:
        return el.inner_text()


def readback(want, got, desc):
    """填进去的正文必须原样读回（忽略空白），否则停。"""
    if browser.norm_text(want) not in browser.norm_text(got):
        raise Abort(u"%s 回读不一致，不发。\n  想填：%s\n  读到：%s"
                    % (desc, want.replace("\n", " ")[:120], (got or "").replace("\n", " ")[:120]))
    log(u"  %s 回读一致" % desc)


def switch_state(el):
    for attr in ("aria-checked", "aria-pressed"):
        v = el.get_attribute(attr)
        if v is not None:
            return v == "true"
    try:
        return el.is_checked()
    except Exception:
        return None


def find_toggle(pg, name_rx, label_rx):
    """先按无障碍名称找开关；找不到再按「唯一的文字标签 + 同一行里唯一的开关」找。"""
    for role in ("switch", "checkbox"):
        v = visible(pg.get_by_role(role, name=name_rx))
        if len(v) == 1:
            return v[0]
    labels = visible(pg.get_by_text(label_rx))
    if len(labels) == 1:
        row = labels[0].locator('xpath=ancestor::*[.//*[@role="switch" or @type="checkbox"]][1]')
        sw = visible(row.locator('[role="switch"], input[type="checkbox"]'))
        if len(sw) == 1:
            return sw[0]
    return None


def ensure_toggle_on(pg, name_rx, label_rx, desc):
    """把开关打开并回读。返回 True=已开 / False=开不上 / None=没找到开关。"""
    el = find_toggle(pg, name_rx, label_rx)
    if el is None:
        log(u"  %s：没找到开关" % desc)
        return None
    st = switch_state(el)
    if st is not True:
        try:
            el.click(timeout=5000)
        except Exception:
            el.click(timeout=5000, force=True)
        pg.wait_for_timeout(1000)
        st = switch_state(el)
    log(u"  %s：%s" % (desc, {True: u"已打开", False: u"仍是关闭", None: u"读不到状态"}[st]))
    return st


# ---------------------------------------------------------------- job 小工具
def hashtags(tags):
    out = []
    for t in tags or []:
        t = re.sub(r"\s+", "", str(t)).lstrip("#")
        if t:
            out.append("#" + t)
    return out


def compose_text(job):
    """正文 = caption + 空一行 + #话题（caption 里已经写了的话题不重复加）。"""
    cap = (job.get("caption") or "").strip()
    tags = [h for h in hashtags(job.get("tags")) if h not in cap]
    return cap + ("\n\n" + " ".join(tags) if tags else "")


def check_files(paths):
    for f in paths or []:
        if not os.path.isfile(f):
            raise Abort(u"文件不存在：%s" % f)


def parse_schedule(s, min_minutes=15, max_days=None):
    """'YYYY-MM-DD HH:MM'（本机时区）→ datetime；空 = 立即发，返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except Exception:
        raise Abort(u"schedule 格式应为 'YYYY-MM-DD HH:MM'，实际是 %r" % s)
    now = datetime.datetime.now()
    if dt < now + datetime.timedelta(minutes=min_minutes):
        raise Abort(u"定时 %s 离现在不到 %d 分钟" % (s, min_minutes))
    if max_days and dt > now + datetime.timedelta(days=max_days):
        raise Abort(u"定时 %s 超过 %d 天以后" % (s, max_days))
    return dt


def ints(s):
    return [int(x) for x in re.findall(r"\d+", s or "")]


# ---------------------------------------------------------------- 登录判断
def login_state(pg, platform):
    """返回 'ok'（已登录）/ 'login'（在登录或验证页）/ 'unknown'（还没加载完或看不出来）。"""
    s = SITES[platform]
    url = (pg.url or "").lower()
    if any(m in url for m in s["login_url"]):
        return "login"
    if visible(pg.locator("input[type=password]")):
        return "login"
    try:
        body = pg.inner_text("body", timeout=5000)
    except Exception:
        body = ""
    if any(t in body for t in s["login_text"]):
        return "login"
    if s.get("ok_sel") and visible(pg.locator(s["ok_sel"])):
        return "ok"
    if any(u in url for u in s.get("ok_url") or ()):
        return "ok"
    return "unknown"


def wait_state(pg, platform, seconds=40):
    end = time.time() + seconds
    st = "unknown"
    while time.time() < end:
        st = login_state(pg, platform)
        if st != "unknown":
            return st
        pg.wait_for_timeout(2000)
    return st


def ensure_logged_in(pg, platform, url=None):
    """打开 url（默认平台首页）并确认已登录；没登录就抛 NotLoggedIn，不再往下走。"""
    s = SITES[platform]
    target = url or s["home"]
    log(u"打开 %s ..." % target)
    pg.goto(target, wait_until="domcontentloaded", timeout=90000)
    st = wait_state(pg, platform, 40)
    if st == "login":
        raise NotLoggedIn(
            u"这个浏览器 profile 还没有登录 %s。\n"
            u"  请先运行：python publish/%s/login.py\n"
            u"  在弹出的窗口里自己登录（脚本不碰密码；用了 --profile 的话两边要写同一个），然后重跑本命令。\n"
            u"  本次什么都没填、什么都没发。" % (s["name"], platform))
    if st != "ok":
        raise Abort(u"40 秒内无法确认 %s 已登录（当前页面：%s）。先运行 login.py 确认登录，"
                    u"或看 _logs 里的截图。本次什么都没发。" % (s["name"], pg.url))
    log(u"  已登录 %s" % s["name"])


# ---------------------------------------------------------------- 入口
def run_login(platform, here, argv):
    """login.py 的公共实现：打开窗口 → 你自己登录 → 每 5 秒检查一次。"""
    jobfile.setup_console()
    _, _, opt = jobfile.parse_args(argv, options=("--profile", "--timeout"))
    s = SITES[platform]
    profile = opt.get("--profile") or os.path.join(here, "_profile")
    timeout = int(float(opt.get("--timeout", 360)))
    from playwright.sync_api import sync_playwright
    ok = False
    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="en-US")
        try:
            try:
                pg.goto(s["home"], wait_until="domcontentloaded", timeout=90000)
            except Exception as e:
                log(u"打开页面出错（继续等待）：%s" % str(e)[:120])
            print("")
            print(u"已打开 %s 的独立浏览器窗口。" % s["name"])
            print(u"-> 请在那个窗口里自己登录（账号密码 / 验证码 / 两步验证都由你自己完成）。")
            print(u"   不用回终端按回车：脚本每 5 秒检查一次，最多等 %d 秒。" % timeout)
            print("")
            waited = 0
            while True:
                st = login_state(pg, platform)
                if st == "ok":
                    ok = True
                    break
                if waited >= timeout:
                    break
                pg.wait_for_timeout(5000)
                waited += 5
                if waited % 30 == 0:
                    print(u"  ...还没检测到登录（已等 %d 秒）" % waited)
            print("")
            if ok:
                print(u"已登录 %s。登录状态保存在：%s" % (s["name"], profile))
                print(u"这个目录等同密码：不要发给别人、不要上传、不要提交到 git。删掉它即退出登录。")
                print(u"下一步：python publish.py --job job.json --dry")
            else:
                print(u"%d 秒内没检测到登录。可能是：" % timeout)
                print(u"  1) 还没登录完 —— 重跑 login.py 继续登录即可；")
                print(u"  2) 平台要求额外验证（短信 / 邮件 / 安全检查）—— 在窗口里完成后重跑 login.py；")
                print(u"  3) 平台拦截了这个浏览器 —— 换个网络或稍后再试。")
                print(u"脚本没有动你的账号，也没有发任何东西。")
            browser.shot(pg, os.path.join(here, "_logs"), "login_check")
        except Exception as e:
            print(u"浏览器窗口被关闭或出错，退出：%s" % str(e)[:160])
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return 0 if ok else 1


USAGE = (u"用法：python publish.py --job job.json --dry       只填不发（先跑这个）\n"
         u"      python publish.py --job job.json --execute   真的发布（必须显式写 --execute）\n"
         u"选项：--profile DIR（默认 ./_profile，要和 login.py 用同一个） --dry-wait 秒（默认 15）")


def run_publish(platform, here, doc, validate, fill, argv=None):
    """publish.py 的公共骨架。

    validate(job)        检查任务字段，有问题抛 Abort（退出码 1，浏览器都不开）
    fill(pg, job, logs)  登录检查 + 填好一切，返回 submit()；fill 里绝不点最终发布按钮
    """
    jobfile.setup_console()
    argv = sys.argv[1:] if argv is None else argv
    pos, flags, opt = jobfile.parse_args(argv, flags=("--dry", "--execute"),
                                         options=("--job", "--profile", "--dry-wait"))
    job_path = opt.get("--job") or (pos[0] if pos else None)
    dry, exe = "--dry" in flags, "--execute" in flags
    if not job_path or dry == exe:
        print(doc)
        print(USAGE)
        return 1
    job = jobfile.load_job(job_path, platform)
    try:
        validate(job)
    except Abort as e:
        log(u"任务文件有问题：%s" % e)
        return 1
    s = SITES[platform]
    logs = os.path.join(here, "_logs")
    profile = opt.get("--profile") or os.path.join(here, "_profile")
    log(u"平台：%s ｜ 任务：%s ｜ 模式：%s" % (s["name"], os.path.basename(job["_job_path"]),
                                         u"DRY（只填不发）" if dry else u"EXECUTE（真发）"))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="en-US")
        try:
            submit = fill(pg, job, logs)
            if dry:
                browser.shot(pg, logs, "dry")
                wait = float(opt.get("--dry-wait", 15))
                log(u"--dry：已填到最后一步，没有点发布。请看窗口 / 截图核对，%d 秒后关闭。" % wait)
                pg.wait_for_timeout(int(wait * 1000))
                return 0
            log(u"--execute：点击最终发布按钮 ...")
            submit()
            browser.shot(pg, logs, "done")
            return 0
        except NotLoggedIn as e:
            log(u"未登录：%s" % e)
            browser.shot(pg, logs, "not_logged_in")
            return 2
        except Abort as e:
            log(u"已中止：%s" % e)
            if exe:
                log(u"提醒：中止不等于没发出去。重跑前先去 %s 的主页 / 定时列表看一眼。" % s["name"])
            browser.shot(pg, logs, "abort")
            return 2
        except Exception as e:
            log(u"意外错误：%s: %s" % (type(e).__name__, str(e)[:300]))
            browser.shot(pg, logs, "error")
            return 3
        finally:
            try:
                ctx.close()
            except Exception:
                pass
