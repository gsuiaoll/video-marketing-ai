"""抖音开放平台 API 封装 — 优先读网页设置，其次读环境变量"""
import json
import hashlib
import hmac
import os
from pathlib import Path
from httpx import Client

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
    return os.getenv(key.upper(), default)


DOUYIN_API_BASE = "https://open.douyin.com"


def get_auth_url(redirect_uri: str, state: str = "") -> str:
    """生成抖音OAuth授权链接"""
    client_key = _get_setting("douyin_client_key")
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": "user_info,trial.whitelist",
        "redirect_uri": redirect_uri,
    }
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    # 先不加 scope，让抖音用默认权限
    return f"{DOUYIN_API_BASE}/platform/oauth/connect/?{qs}"


def exchange_code(code: str) -> dict:
    """用授权码换取 access_token"""
    client_key = _get_setting("douyin_client_key")
    client_secret = _get_setting("douyin_client_secret")
    client = Client(timeout=30)
    resp = client.get(f"{DOUYIN_API_BASE}/oauth/access_token/", params={
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code"
    })
    resp.raise_for_status()
    data = resp.json()
    if data.get("data", {}).get("error_code", 0) != 0:
        raise RuntimeError(f"抖音OAuth失败: {data}")
    return data["data"]


def send_private_message(access_token: str, to_user_id: str, content: str) -> dict:
    """发送抖音私信"""
    client = Client(timeout=15)
    resp = client.post(
        f"{DOUYIN_API_BASE}/message/once/send/",
        params={"access_token": access_token},
        json={
            "to_user_id": to_user_id,
            "message_type": "text",
            "content": content
        }
    )
    resp.raise_for_status()
    return resp.json()


def fetch_user_videos(access_token: str, open_id: str, count: int = 20) -> list[dict]:
    """拉取用户已发布的视频列表"""
    client = Client(timeout=30)
    try:
        resp = client.get(f"{DOUYIN_API_BASE}/video/list/", params={
            "access_token": access_token,
            "open_id": open_id,
            "count": count,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("data", {}).get("error_code", 0) != 0:
            return []
        return data.get("data", {}).get("list", [])
    except Exception:
        return []


def fetch_video_stats(access_token: str, open_id: str, item_ids: list) -> dict:
    """批量拉取视频数据（播放量等）"""
    if not item_ids:
        return {}
    client = Client(timeout=30)
    try:
        resp = client.post(f"{DOUYIN_API_BASE}/video/data/", params={
            "access_token": access_token,
            "open_id": open_id,
        }, json={"item_ids": item_ids})
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("list", [])
    except Exception:
        return []


def get_video_jump_url(access_token: str, open_id: str, item_id: str) -> str:
    """获取视频跳转链接（用于分享或预览）"""
    client = Client(timeout=15)
    try:
        resp = client.post(f"{DOUYIN_API_BASE}/share/item/jump/", params={
            "access_token": access_token,
            "open_id": open_id,
        }, json={"item_id": item_id})
        resp.raise_for_status()
        data = resp.json()
        if data.get("data", {}).get("error_code", 0) != 0:
            return ""
        return data.get("data", {}).get("share_url", "")
    except Exception:
        return ""


def share_to_message(access_token: str, open_id: str, to_open_id: str, item_id: str = "", title: str = "") -> bool:
    """分享视频到抖音私信"""
    client = Client(timeout=15)
    try:
        body = {}
        if item_id:
            body["item_id"] = item_id
        if title:
            body["title"] = title
        body["to_open_id"] = to_open_id
        resp = client.post(f"{DOUYIN_API_BASE}/share/direct_message/send/", params={
            "access_token": access_token,
            "open_id": open_id,
        }, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("error_code", 0) == 0
    except Exception:
        return False


def forward_to_douyin(access_token: str, open_id: str, item_id: str) -> dict:
    """转发内容到抖音以日常作品形式发布"""
    client = Client(timeout=15)
    try:
        resp = client.post(f"{DOUYIN_API_BASE}/aweme/forward/create/", params={
            "access_token": access_token,
            "open_id": open_id,
        }, json={"item_id": item_id})
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception:
        return {}


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """验证抖音Webhook签名"""
    client_secret = _get_setting("douyin_client_secret")
    if not client_secret:
        return False
    expected = hmac.new(
        client_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
