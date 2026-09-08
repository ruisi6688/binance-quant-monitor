# -*- coding: utf-8 -*-
"""钉钉机器人通知模块
用法: from notify import send_dingtalk; send_dingtalk("标题", "内容")
"""
import json
import urllib.request

# 在这里填入你的钉钉 Webhook（或通过 DINGTALK_WEBHOOK 环境变量传入）
WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=YOUR_DINGTALK_WEBHOOK_TOKEN"


def send_dingtalk(title, content, webhook=None):
    """发送钉钉机器人消息，成功返回 True。"""
    wh = webhook or WEBHOOK
    if not wh:
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": "### {}\n\n{}".format(title, content),
        },
    }
    try:
        req = urllib.request.Request(
            wh,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("errcode") == 0
    except Exception as e:
        print("[notify] 发送失败:", e)
        return False


if __name__ == "__main__":
    # 测试发送
    ok = send_dingtalk("测试通知", "钉钉机器人连接成功！✅")
    print("发送结果:", "成功" if ok else "失败")
