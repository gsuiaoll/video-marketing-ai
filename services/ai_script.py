"""OpenClaw Agent 统一调用 — 满血版：持久会话 + 多步推理 + Browser + 文件读写"""

import json
import subprocess
import shutil
import os
import hashlib
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent.parent / "data" / "settings.json"
WORKSPACE_DIR = Path(__file__).parent.parent / "data" / "agent_workspace"

# ── 持久会话管理 ──
def _session_key(context: str, *parts: str) -> str:
    """生成稳定的 session key，持久会话跨请求复用上下文"""
    key = f"{context}:{':'.join(parts)}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


# ── 统一 AI 调用 ──
def call_ai(prompt: str, system: str = "你是一个专业的商业信息助手。",
            temperature: float = 0.7, enable_search: bool = False,
            context: str = "general", merchant_id: str = "",
            enable_browser: bool = False) -> str | None:
    """OpenClaw Agent 满血调用 — 持久会话 + 联网搜索 + Browser + 多步推理"""
    result = _call_openclaw_local(
        prompt, system, enable_search,
        context=context, merchant_id=merchant_id,
        enable_browser=enable_browser
    )
    if result:
        return result

    # 回退：Qwen/DeepSeek HTTP 直连
    api_key = _get_api_key()
    if not api_key:
        return None
    from httpx import Client
    from config import QWEN_BASE_URL, QWEN_MODEL
    client = Client(base_url=QWEN_BASE_URL, timeout=90)
    body = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
    }
    if enable_search:
        body["enable_search"] = True
    try:
        resp = client.post("/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"}, json=body)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None


def _call_openclaw_local(prompt: str, system: str = "", enable_search: bool = False,
                         context: str = "general", merchant_id: str = "",
                         enable_browser: bool = False) -> str | None:
    """OpenClaw --local agent：持久会话 + 工具调用"""
    openclaw_bin = shutil.which("openclaw")
    if not openclaw_bin:
        return None

    session_id = _session_key(context, merchant_id)

    hints = []
    if enable_search:
        hints.append("请用web_search工具搜索真实信息，不编造")
    if enable_browser:
        hints.append("可用browser工具打开网页查看详情")
    if hints:
        full_message = f"{system}\n\n{'；'.join(hints)}。\n\n{prompt}" if system else f"{'；'.join(hints)}。\n\n{prompt}"
    else:
        full_message = f"{system}\n\n{prompt}" if system else prompt

    # 代理
    env = {**os.environ}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7897"
    if proxy:
        env.setdefault("HTTPS_PROXY", proxy)
        env.setdefault("HTTP_PROXY", proxy)

    # Workspace
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    env.setdefault("OPENCLAW_WORKSPACE", str(WORKSPACE_DIR))

    try:
        proc = subprocess.run(
            [openclaw_bin, "agent", "--local", "--json",
             "-m", full_message,
             "--session-key", session_id],
            capture_output=True, text=True, timeout=180, env=env
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            payloads = data.get("payloads", [])
            if payloads and payloads[0].get("text"):
                return payloads[0]["text"]
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return None


# ── 多 Agent 并行（分维度搜索 → 汇总）──
def call_multi_agent(merchant_name: str, district: str, industry: str = "",
                     context: str = "merchant_enrich") -> dict:
    """多维度并行搜索商家信息，返回结构化结果"""
    dimensions = [
        ("base", f"用web_search搜索'{merchant_name} {district} {industry}'，获取工商信息、主营产品"),
        ("reviews", f"用web_search搜索'{merchant_name} 评价 口碑 客户反馈'，了解客户评价"),
        ("news", f"用web_search搜索'{merchant_name} 2026 最新动态 活动'，获取近期情况"),
    ]
    results = {}
    for dim, search_prompt in dimensions:
        result = call_ai(
            search_prompt,
            system="你是商业调研助手。用web_search搜索后，用2-3句话总结关键信息。只输出摘要，不要多余内容。",
            enable_search=True, context=context, merchant_id=merchant_name
        )
        if result:
            results[dim] = result

    if not results:
        return {}

    # 汇总
    summary_prompt = f"""基于以下搜索结果，为"{merchant_name}"填写商家画像：

{" ".join(f"[{k}]: {v}" for k, v in results.items())}

按格式输出：
主打产品/菜品：
近期情况：
业务模式：
服务特色：
目标客户：
竞争优势：
推广活动：
拍摄备注："""

    summary = call_ai(summary_prompt,
        system="你是商业信息整理专家。基于搜索结果如实用中文填写，每项20-50字。",
        context=context, merchant_id=merchant_name)

    enrich = {}
    if summary:
        for line in summary.strip().split("\n"):
            for key in ["主打产品/菜品：", "近期情况：", "业务模式：", "服务特色：",
                       "目标客户：", "竞争优势：", "推广活动：", "拍摄备注："]:
                if line.strip().startswith(key):
                    val = line.strip()[len(key):].strip()
                    if val and val not in ("无", "暂无"):
                        enrich[key.replace("：", "")] = val
    return enrich


# ── 浏览器自动化 ──
def call_browser(url: str, instruction: str, context: str = "browser") -> str | None:
    """用 Browser 工具打开网页并执行操作"""
    prompt = f"""打开网址 {url}，执行以下操作：
{instruction}

完成后用文字总结你看到的页面内容。"""
    return call_ai(prompt,
        system="你是网页分析助手。用browser工具打开网页、查看内容、提取关键信息。",
        enable_browser=True, context=context)


def _get_api_key() -> str:
    from config import QWEN_API_KEY
    key = _get_setting("deepseek_api_key") or _get_setting("qwen_api_key")
    return key or QWEN_API_KEY


def _get_setting(key: str, default: str = "") -> str:
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            val = data.get(key, "")
            if val:
                return val
    except Exception:
        pass
    return default


# ── 定时任务：每周自动更新商家画像 ──
def scheduled_merchant_refresh(merchant_name: str, district: str = "", industry: str = "") -> dict | None:
    """定时任务入口：搜索商家最新动态并返回更新内容"""
    result = call_ai(
        f"用web_search搜索'{merchant_name} {district} 2026年7月 最新动态 活动 促销'，"
        f"总结2-3条最新信息，用于更新商家画像的'近期情况'字段。只输出内容，不要编号。",
        system="你是商家信息监控助手，定期搜索商家最新动态。",
        enable_search=True, context="cron_refresh", merchant_id=merchant_name
    )
    if result:
        return {"近期情况": result.strip()}
    return None


# ── 视频脚本生成（兼容旧接口）──
SYSTEM_PROMPT = """你是一个专业的短视频拍摄脚本撰写专家。
你的任务是根据商家信息生成高质量的结构化拍摄脚本。
输出 JSON 格式：
{
  "title": "视频标题",
  "hook": "前3秒钩子话术",
  "shots": [{"description": "画面描述", "lines": "台词/旁白", "duration_sec": 5}],
  "cta": "结尾行动号召",
  "tags": ["标签1", "标签2", "标签3"]
}"""


def _build_profile_context(profile: dict) -> str:
    if not profile:
        return ""
    field_labels = {
        "products_dishes": "菜品/产品", "recent_updates": "近期情况",
        "business_model": "业务模式", "service_features": "服务特色",
        "target_customers": "目标客户", "competitive_advantages": "竞争优势",
        "promotions": "推广活动", "shooting_notes": "拍摄备注",
    }
    parts = []
    for key, label in field_labels.items():
        val = (profile.get(key) or "").strip()
        if val:
            parts.append(f"- {label}: {val}")
    return "\n".join(parts)


def _build_few_shot(examples: list[dict]) -> str:
    if not examples:
        return ""
    parts = ["\n\n=== 优秀脚本示例 ===\n"]
    for i, ex in enumerate(examples, 1):
        parts.append(f"【示例{i}】{ex.get('title', '')}")
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
    """调用 AI 生成拍摄脚本"""
    user_prompt = f"""请为以下商家生成一个{platform}平台的短视频拍摄脚本：

商家名称：{merchant_name}
行业：{industry}
产品/服务卖点：{product_info}
目标时长：{duration_sec}秒"""

    profile_ctx = _build_profile_context(merchant_profile or {})
    if profile_ctx:
        user_prompt += profile_ctx
    if extra_requirements:
        user_prompt += f"\n额外要求：{extra_requirements}"

    few_shot = _build_few_shot(starred_examples or [])
    system_with_examples = SYSTEM_PROMPT + few_shot

    try:
        result = call_ai(user_prompt, system=system_with_examples, temperature=0.8,
                        context="script_gen", merchant_id=merchant_name)
        if result:
            import re as _re
            json_match = _re.search(r'\{[\s\S]*\}', result)
            if json_match:
                return json.loads(json_match.group(0))
    except Exception:
        pass
    return {}
