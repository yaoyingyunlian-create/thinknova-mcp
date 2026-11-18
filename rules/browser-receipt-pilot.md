# 浏览器发布回执试跑

1. 用客户工作目录里的实际工具包执行 `git rev-parse HEAD` 和 `python toolkit.py verify`。列出试跑项目实际授权的平台、账号名或 ID、主页链接和登录状态。主页链接另列，计划字段 `targets` 只填账号名或 ID。
2. 使用同一份经过质检的有声 1080×1920 MP4，保留与 MP4 对应的 `.film.json`。用 `python browser_receipt.py init receipt.json final.mp4 plan.json` 创建回执。计划填 `project_key`、当地日期 `local_date`，以及各平台与账号的 `targets` 映射。
3. 逐平台选择短视频入口与 9:16 原始比例，按现场要求披露 AI 内容。回看已发作品的竖屏、人物和声音。结果未知先查原帖，裁切异常先记录，删除或补发须在当前授权内。
4. 用 `python browser_receipt.py record receipt.json 平台 event.json` 记录每个平台。发布成功填写 `status: "published"`、`post_url`、带时区的 `published_at`、`portrait`、`sound`、`subject_visible`。掉登录写 `login_required` 和脱敏 `failure_reason`，其余平台继续。已补发写 `retried: true`。
5. 用 `python browser_receipt.py sync receipt.json` 上报。以 `synced`、`receipt_id` 和后台对应平台行确认。若为 `local_only` 或 `queued`，保留文件与安全错误码，恢复后补报。运营分别核对每天回执齐全和实际发布成功。

## English

Verify the active checkout, film digest, targets and signed-in accounts. Keep account handles or IDs in the plan and profile links in the operator notes. Record a separate outcome for each platform. Verify uncertain outcomes before retrying. Sign-in failures affect only the corresponding platform. Confirm both the synced receipt ID and its rows in the dashboard before marking the trial complete.
