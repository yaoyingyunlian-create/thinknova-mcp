# -*- coding: utf-8 -*-
"""Facebook（Meta Business Suite） 登录 —— 你自己手动登录一次，之后 publish.py 复用这个浏览器 profile。

    python login.py
    python login.py --profile 某个目录      # 自定义 profile 目录（publish.py 也要写同一个）
    python login.py --timeout 600           # 最多等几秒（默认 360）

做什么：
  1. 打开一个独立的、可见的浏览器窗口，进入 https://business.facebook.com/latest/home
  2. 你在窗口里自己登录（账号密码、验证码、两步验证都由你完成）
  3. 脚本每 5 秒检查一次是否已登录，登录成功就保存并退出

脚本从不输入密码、不处理验证码、不创建账号。
profile 目录（默认 ./_profile）里是你的登录会话，等同密码：不要发给别人、不要上传、不要提交到 git。
删掉这个目录即退出登录；再跑一次本脚本即可重新登录。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import social  # noqa: E402

if __name__ == "__main__":
    sys.exit(social.run_login("facebook", HERE, sys.argv[1:]))
