"""巨量引擎 Marketing API 服务 — 广告报表 + Token 管理"""
import json
import time
from pathlib import Path
from httpx import Client

SETTINGS_FILE = Path(__file__).parent.parent / "data" / "settings.json"
API_BASE = "https://api.oceanengine.com"


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_settings(data: dict):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings()
    existing.update(data)
    SETTINGS_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_setting(key: str, default: str = "") -> str:
    return _load_settings().get(key, default)


def get_auth_url(app_id: str, redirect_uri: str) -> str:
    """生成巨量引擎 OAuth 授权链接"""
    return (
        f"https://open.oceanengine.com/audit/app-auth/get-auth?"
        f"app_id={app_id}&redirect_uri={redirect_uri}&state=oceanengine"
    )


def exchange_token(app_id: str, app_secret: str, auth_code: str) -> dict | None:
    """用授权码换取 access_token + refresh_token"""
    client = Client(base_url=API_BASE, timeout=30)
    try:
        resp = client.post("/open_api/oauth2/access_token/", json={
            "app_id": int(app_id),
            "secret": app_secret,
            "grant_type": "auth_code",
            "auth_code": auth_code,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Token exchange failed: {data.get('message', data)}")
        token_data = data.get("data", {})
        # Save tokens
        _save_settings({
            "oceanengine_access_token": token_data.get("access_token", ""),
            "oceanengine_refresh_token": token_data.get("refresh_token", ""),
        })
        return token_data
    except Exception as e:
        raise RuntimeError(f"巨量引擎 Token 获取失败: {e}")


def ensure_token() -> str:
    """确保 token 有效，过期自动刷新"""
    token = _get_setting("oceanengine_access_token", "")
    if not token:
        # Try refresh
        refresh = _get_setting("oceanengine_refresh_token", "")
        if refresh:
            return _do_refresh(refresh)
        raise RuntimeError("未配置巨量引擎 Token，请先授权")
    return token


def _do_refresh(refresh_token: str) -> str:
    """刷新 access_token（refresh_token 会轮换）"""
    app_id = _get_setting("oceanengine_app_id", "")
    app_secret = _get_setting("oceanengine_app_secret", "")
    client = Client(base_url=API_BASE, timeout=30)
    try:
        resp = client.post("/open_api/oauth2/refresh_token/", json={
            "app_id": int(app_id),
            "secret": app_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Token refresh failed: {data.get('message', data)}")
        token_data = data.get("data", {})
        _save_settings({
            "oceanengine_access_token": token_data.get("access_token", ""),
            "oceanengine_refresh_token": token_data.get("refresh_token", ""),
        })
        return token_data.get("access_token", "")
    except Exception as e:
        raise RuntimeError(f"巨量引擎 Token 刷新失败: {e}")


def fetch_advertiser_info(advertiser_id: str) -> dict:
    """获取广告主基本信息"""
    token = ensure_token()
    client = Client(base_url=API_BASE, timeout=30)
    try:
        resp = client.get("/v3.0/advertiser/info/", params={
            "advertiser_ids": [advertiser_id],
        }, headers={"Access-Token": token})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data.get('message', '')}")
        return data.get("data", {}).get("list", [{}])[0]
    except Exception as e:
        raise RuntimeError(f"获取广告主信息失败: {e}")


def fetch_report(start_date: str, end_date: str, advertiser_id: str = "", page_size: int = 50) -> dict:
    """
    拉取广告报表数据。
    start_date / end_date: "YYYY-MM-DD"
    返回: {summary: {cost, show, click, convert, ...}, details: [...]}
    """
    token = ensure_token()
    aid = advertiser_id or _get_setting("oceanengine_advertiser_id", "")
    if not aid:
        return {"summary": {}, "details": [], "error": "未配置广告主 ID"}

    client = Client(base_url=API_BASE, timeout=30)
    try:
        resp = client.get("/v3.0/report/advertiser/get/", params={
            "advertiser_id": int(aid),
            "start_date": start_date,
            "end_date": end_date,
            "page": 1,
            "page_size": page_size,
        }, headers={"Access-Token": token})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            # Try token refresh and retry once
            refresh = _get_setting("oceanengine_refresh_token", "")
            if refresh and data.get("code") == 401:
                new_token = _do_refresh(refresh)
                resp = client.get("/v3.0/report/advertiser/get/", params={
                    "advertiser_id": int(aid),
                    "start_date": start_date,
                    "end_date": end_date,
                    "page": 1,
                    "page_size": page_size,
                }, headers={"Access-Token": new_token})
                resp.raise_for_status()
                data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Report API error: {data.get('message', '')}")

        report_data = data.get("data", {})

        # Aggregate summary
        rows = report_data.get("list", [])
        summary = {
            "cost": 0.0,
            "show": 0,
            "click": 0,
            "convert": 0,
            "convert_cost": 0.0,
            "ctr": 0.0,
        }
        for row in rows:
            summary["cost"] += float(row.get("stat_cost", 0))
            summary["show"] += int(row.get("stat_show", 0))
            summary["click"] += int(row.get("stat_click", 0))
            summary["convert"] += int(row.get("stat_convert", 0))

        if summary["cost"] > 0 and summary["convert"] > 0:
            summary["convert_cost"] = round(summary["cost"] / summary["convert"], 2)
        if summary["show"] > 0:
            summary["ctr"] = round(summary["click"] / summary["show"] * 100, 2)

        return {
            "summary": summary,
            "details": rows,
            "date_range": f"{start_date} ~ {end_date}",
        }
    except Exception as e:
        return {"summary": {}, "details": [], "error": str(e)}


def fetch_campaign_report(start_date: str, end_date: str, advertiser_id: str = "") -> dict:
    """拉取按广告组拆分的报表"""
    token = ensure_token()
    aid = advertiser_id or _get_setting("oceanengine_advertiser_id", "")
    if not aid:
        return {"details": [], "error": "未配置广告主 ID"}

    client = Client(base_url=API_BASE, timeout=30)
    try:
        resp = client.get("/v3.0/report/campaign/get/", params={
            "advertiser_id": int(aid),
            "start_date": start_date,
            "end_date": end_date,
            "page": 1,
            "page_size": 50,
        }, headers={"Access-Token": token})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            # Refresh and retry
            refresh = _get_setting("oceanengine_refresh_token", "")
            if refresh:
                new_token = _do_refresh(refresh)
                resp = client.get("/v3.0/report/campaign/get/", params={
                    "advertiser_id": int(aid),
                    "start_date": start_date,
                    "end_date": end_date,
                    "page": 1,
                    "page_size": 50,
                }, headers={"Access-Token": new_token})
                resp.raise_for_status()
                data = resp.json()
            if data.get("code") != 0:
                return {"details": [], "error": data.get("message", "")}

        return {
            "details": data.get("data", {}).get("list", []),
            "date_range": f"{start_date} ~ {end_date}",
        }
    except Exception as e:
        return {"details": [], "error": str(e)}


def fetch_report_for_account(start_date: str, end_date: str, advertiser_id: str, access_token: str) -> dict:
    """用指定账户的 token 拉取报表（多账户模式）"""
    client = Client(base_url=API_BASE, timeout=30)
    try:
        resp = client.get("/v3.0/report/advertiser/get/", params={
            "advertiser_id": int(advertiser_id),
            "start_date": start_date,
            "end_date": end_date,
            "page": 1,
            "page_size": 50,
        }, headers={"Access-Token": access_token})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return {"summary": {}, "details": [], "error": data.get("message", "")}

        rows = data.get("data", {}).get("list", [])
        summary = {"cost": 0.0, "show": 0, "click": 0, "convert": 0, "convert_cost": 0.0, "ctr": 0.0}
        for row in rows:
            summary["cost"] += float(row.get("stat_cost", 0))
            summary["show"] += int(row.get("stat_show", 0))
            summary["click"] += int(row.get("stat_click", 0))
            summary["convert"] += int(row.get("stat_convert", 0))
        if summary["cost"] > 0 and summary["convert"] > 0:
            summary["convert_cost"] = round(summary["cost"] / summary["convert"], 2)
        if summary["show"] > 0:
            summary["ctr"] = round(summary["click"] / summary["show"] * 100, 2)
        return {"summary": summary, "details": rows}
    except Exception as e:
        return {"summary": {}, "details": [], "error": str(e)}


def refresh_account_token(advertiser_id: str, refresh_token: str) -> str:
    """刷新指定账户的 access_token"""
    app_id = _get_setting("oceanengine_app_id", "")
    app_secret = _get_setting("oceanengine_app_secret", "")
    client = Client(base_url=API_BASE, timeout=30)
    try:
        resp = client.post("/open_api/oauth2/refresh_token/", json={
            "app_id": int(app_id),
            "secret": app_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Token refresh failed: {data.get('message', '')}")
        return data.get("data", {}).get("access_token", "")
    except Exception:
        return ""
