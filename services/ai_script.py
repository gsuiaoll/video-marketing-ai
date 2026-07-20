import json
from pathlib import Path
from httpx import Client
from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL

SETTINGS_FILE = Path(__file__).parent.parent / "data" / "settings.json"


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

SYSTEM_PROMPT = """你是一个专业的短视频拍摄脚本撰写专家。你的任务是根据商家信息（包括商家画像中的业务模式、服务特色、目标客户等），生成高质量的结构化拍摄脚本。

要求：
1. 钩子（前3秒）必须抓眼球，用悬念/冲突/痛点开头
2. 分镜描述要具体可执行，包含画面、台词、时长
3. 结尾CTA要有明确的行动指引
4. 语言风格适配目标平台（抖音口语化/视频号偏正式）
5. 充分利用「商家详细信息」中的菜品、业务模式、服务特色、目标客户等信息，让脚本内容贴合商家实际情况

请严格按照以下JSON格式输出，不要输出其他内容：
{
  "title": "视频标题",
  "hook": "前3秒钩子话术",
  "shots": [
    {"description": "画面描述", "lines": "台词/旁白", "duration_sec": 5}
  ],
  "cta": "结尾行动号召",
  "tags": ["标签1", "标签2", "标签3"]
}"""


def _build_profile_context(profile: dict) -> str:
    """把商家画像字段拼成上下文注入 prompt"""
    if not profile:
        return ""
    field_labels = {
        "products_dishes": "菜品/产品",
        "recent_updates": "近期情况",
        "business_model": "业务模式",
        "service_features": "服务特色",
        "target_customers": "目标客户",
        "competitive_advantages": "竞争优势",
        "promotions": "推广活动",
        "shooting_notes": "拍摄备注",
    }
    parts = []
    for key, label in field_labels.items():
        val = (profile.get(key) or "").strip()
        if val:
            parts.append(f"- {label}: {val}")
    if not parts:
        return ""
    return "\n\n=== 商家详细信息（来自商家画像数据库） ===\n" + "\n".join(parts)


def _build_few_shot(examples: list[dict]) -> str:
    """把标星脚本拼成 few-shot 示例注入 prompt"""
    if not examples:
        return ""

    parts = ["\n\n=== 以下是你之前写过的优秀脚本，请参考其风格和质量 ===\n"]
    for i, ex in enumerate(examples, 1):
        parts.append(f"【优秀示例{i}】{ex.get('title', '')}")
        parts.append(f"钩子: {ex.get('hook', '')}")
        shots = ex.get("shots", [])
        if shots:
            parts.append(f"分镜({len(shots)}个):")
            for s in shots:
                parts.append(f"  - {s.get('description','')} | {s.get('lines','')} | {s.get('duration_sec',0)}秒")
        parts.append("")
    return "\n".join(parts)


def generate_script(merchant_name: str, industry: str, product_info: str,
                    platform: str = "douyin", duration_sec: int = 60,
                    extra_requirements: str = "",
                    starred_examples: list[dict] | None = None,
                    merchant_profile: dict | None = None) -> dict:
    """调用 AI 生成拍摄脚本，自动注入商家画像和标星脚本作为上下文"""

    user_prompt = f"""请为以下商家生成一个{platform}平台的短视频拍摄脚本：

商家名称：{merchant_name}
行业：{industry}
产品/服务卖点：{product_info}
目标时长：{duration_sec}秒"""

    # 注入商家画像
    profile_ctx = _build_profile_context(merchant_profile or {})
    if profile_ctx:
        user_prompt += profile_ctx

    if extra_requirements:
        user_prompt += f"\n额外要求：{extra_requirements}"

    # 标星脚本经验注入
    few_shot = _build_few_shot(starred_examples or [])
    system_with_examples = SYSTEM_PROMPT + few_shot

    client = Client(base_url=QWEN_BASE_URL, timeout=60)
    api_key = _get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = client.post(
            "/chat/completions",
            headers=headers,
            json={
                "model": QWEN_MODEL,
                "messages": [
                    {"role": "system", "content": system_with_examples},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.8,
                "response_format": {"type": "json_object"}
            }
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        raise RuntimeError(f"AI脚本生成失败: {e}")
