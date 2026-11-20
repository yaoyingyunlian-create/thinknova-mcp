"""The toolkit produces videos; the customer's AI assistant owns scheduling and publishing."""
import json

PUBLICATION_MOVED = 'PUBLICATION_MOVED_TO_ASSISTANT_EGO'
SCHEDULING_MOVED = 'SYSTEM_SCHEDULING_REMOVED_USE_ASSISTANT'


def handoff(reason=PUBLICATION_MOVED):
    return {'status':'external_workflow','reason_code':reason,
            'scheduler':'customer_ai_assistant','browser':'ego_lite',
            'message':'工具包只制作视频。请由客户AI助理的原生定时任务触发，并通过Ego Lite核对账号、内容和授权后发布。',
            'message_en':'The toolkit makes videos. Use the customer AI assistant scheduler and Ego Lite for authorized publishing.'}


def retired_publication():
    print(json.dumps(handoff(),ensure_ascii=False))
    return 2
