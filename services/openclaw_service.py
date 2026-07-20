"""
AI 客服服务

默认调用 DeepSeek/Qwen API 做智能客服回复。
如果没配 API Key，自动降级到关键词匹配 Mock 模式。
"""
import json
import os
from pathlib import Path
from httpx import Client
from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL

SETTINGS_FILE = Path(__file__).parent.parent / "data" / "settings.json"

OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://localhost:3001")
OPENCLAW_MOCK = os.getenv("OPENCLAW_MOCK", "").lower() == "true"


def _get_setting(key: str, default: str = "") -> str:
    """优先读网页设置的 JSON，其次读环境变量"""
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            val = data.get(key, "")
            if val:
                return val
    except Exception:
        pass
    return default


def _get_api_key() -> str:
    """获取 API Key: 优先 DeepSeek，其次 Qwen"""
    key = _get_setting("deepseek_api_key") or _get_setting("qwen_api_key")
    return key or QWEN_API_KEY

CS_SYSTEM_PROMPT = """你是一个专业的短视频代运营公司客服「小龙虾」🦞，负责回复签约商家的咨询。

你的特点：
1. 热情、专业、口语化，像真人客服一样聊天
2. 了解短视频运营行业（抖音、视频号、TikTok等平台）
3. 能回答关于脚本撰写、视频拍摄、账号运营、投流推广等问题
4. 对于退款、投诉等敏感问题，要道歉 + 安抚 + 转人工
5. 回复简洁，控制在 2-3 句话，不要太长

请严格按以下 JSON 格式输出，不要输出其他内容：
{
  "reply": "回复内容",
  "confidence": 0.85,
  "intent": "意图类别",
  "needs_human": false
}

意图类别：greeting | product_inquiry | pricing | script_help | video_help | ad_help | refund | complaint | general"""


def _call_ai(user_name: str, content: str) -> dict:
    """调用 AI API 做智能客服回复"""
    user_prompt = f"""用户名称：{user_name}
用户消息：{content}

请以小龙虾客服的身份回复这条消息。"""

    client = Client(base_url=QWEN_BASE_URL, timeout=30)
    api_key = _get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = client.post(
            "/chat/completions",
            headers=headers,
            json={
                "model": QWEN_MODEL,
                "messages": [
                    {"role": "system", "content": CS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"}
            }
        )
        resp.raise_for_status()
        data = resp.json()
        content_str = data["choices"][0]["message"]["content"]
        result = json.loads(content_str)
        return {
            "reply": result.get("reply", "感谢您的咨询，请问有什么可以帮助您的？"),
            "confidence": result.get("confidence", 0.8),
            "intent": result.get("intent", "general"),
            "kb_sources": [],
            "needs_human": result.get("needs_human", False)
        }
    except Exception:
        # API 调用失败 → 降级到关键词匹配
        return _mock_reply("", user_name, content)


def process_message(
    platform: str,
    user_id: str,
    user_name: str,
    content: str,
    conversation_id: str = ""
) -> dict:
    """
    处理用户消息，返回 AI 回复。

    返回格式:
    {
        "reply": "回复文本",
        "confidence": 0.92,
        "intent": "product_inquiry",
        "kb_sources": [],
        "needs_human": False
    }
    """
    # 强制 Mock 模式 或 没配 API Key → 降级
    api_key = _get_api_key()
    if OPENCLAW_MOCK or not api_key:
        return _mock_reply(platform, user_name, content)

    return _call_ai(user_name, content)


def get_conversations(status: str = "open") -> list:
    """获取会话列表（阶段一用内存存储，暂不持久化）"""
    return []


def _mock_reply(platform: str, user_name: str, content: str) -> dict:
    """关键词匹配降级（无 API Key 时的兜底方案）"""
    greetings = ["你好", "在吗", "您好", "hello", "hi", "请问"]
    is_greeting = any(content.strip().lower().startswith(g) for g in greetings)

    if is_greeting:
        return {
            "reply": f"您好{user_name}！感谢您的咨询，请问有什么可以帮助您的？",
            "confidence": 0.95,
            "intent": "greeting",
            "kb_sources": [],
            "needs_human": False
        }

    intent_map = {
        "价格": ("关于价格方面，我们的产品性价比很高，具体价格取决于您的需求方案。方便的话可以留个联系方式，我们详细沟通。", "pricing"),
        "怎么": ("感谢您的咨询！我们的产品操作简单，您可以先看看介绍视频。有什么具体问题我可以帮您解答。", "product_inquiry"),
        "退款": ("非常抱歉给您带来了不便。关于退款，请您稍等，我让客服专员为您处理。", "refund"),
        "投诉": ("非常抱歉！我马上为您转接专属客服处理，请您稍等片刻。", "complaint"),
    }

    for keyword, (reply, intent) in intent_map.items():
        if keyword in content:
            return {
                "reply": reply,
                "confidence": 0.75,
                "intent": intent,
                "kb_sources": [],
                "needs_human": intent in ("refund", "complaint")
            }

    return {
        "reply": "感谢您的留言！您的问题已收到，我会尽快为您解答。如有紧急需求，可直接联系我们客服电话。",
        "confidence": 0.6,
        "intent": "general",
        "kb_sources": [],
        "needs_human": True
    }
