> 历史规则说明。当前工具包只制作视频；定时与发布使用客户AI助理和Ego Lite，见AGENTS.md。 Historical note: current scope is video production only.

# v3.1.20：修订59与质量政策58

新设备日计划请求版本8，旧计划使用原契约。产品或服务明确、套餐及批准预算可用时，缺店名、照片、原话或完整卖点不等待补齐。缺照片生成示意画面，不捏造真实招牌、地址、包装或顾客案例。

日计划先返回 preparing 和有序 asset_preparation。工具包报价、准备素材，再通过 /mcp/device/day-plan/materialize 绑定成功任务。服务端限定账户、项目和运行；全部素材就绪后继续原视频链路。运行和素材请求号不可因断网改变。规格预估不是正式报价；正式任务始终执行逐项报价及 max_credits，总费用包括图片、视频和已批准的恢复。

只有服务器返回 quality_policy.version=58 才启用新检查。严重损坏、错误规格、近全黑、无声音和已测低于30%的对白匹配会阻断；语速、停顿、短暂空白、低运动及30%～80%匹配记警告。自动裁边界空白并同步字幕，不用末帧补时长。

转写自动修复一次仍失败时记录 unknown，而非合格发音；有效自动发布授权允许继续，普通待审不变。两次本地错配核验后最多一次预算内新生成，仍失败改局部无对白加字幕。整条无声仍不能发布。库存仅复用同项目、同规则版本、账号一致、未过期且无已知提交记录的作品，未知发布结果先核验。

凭据只证明文件摘要和对应政策结果，不证明客户无法修改工具包、人物绝对一致或语音已实际回听。真正的 Windows/Mac、客户样片和发布验收另记。不要将模型生成修复称为免费重试，也不要在升级时扩大授权或登记系统任务。

## English

Day-plan request version 8 uses revision 59. A known product/service and approved funds are sufficient; missing shop names, photos and quotes become a delivery checklist. Automatically quote and prepare illustrative images, then materialize successful tasks within the current account/project/run. Existing plans keep their original contract and request IDs.

Only server policy 58 enables relaxed quality checks. Unusable media or measured dialogue agreement below 30% block; pacing, pauses and 30–80% agreement warn. After one bounded speech-runtime repair, unavailable recognition is explicitly unknown. An existing publication grant may continue; ordinary first-film review remains. Two local mismatch checks permit at most one budgeted new generation, then a caption-only shot fallback. A wholly silent film still fails.

Use only matching, unexpired, locally unattempted inventory and reserve it before use. Hash-bound policy receipts and warnings accompany delivery/publication. No real-device, model-quality or actual publication acceptance is implied by local tests.
