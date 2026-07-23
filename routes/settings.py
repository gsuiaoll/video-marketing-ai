"""系统设置页 — 在线修改 API 密钥，无需重启"""
import json
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/settings", tags=["设置"])

SETTINGS_FILE = Path(__file__).parent.parent / "data" / "settings.json"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return {}


def save_settings(data: dict):
    existing = load_settings()
    existing.update(data)
    SETTINGS_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("")
def settings_page(request: Request):
    from routes.merchants import check_auth
    check_auth(request)
    s = load_settings()
    templates = get_templates()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": s,
        "saved": request.query_params.get("saved", "")
    })


@router.post("")
async def save_settings_route(request: Request):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    data = {
        "douyin_client_key": form.get("douyin_client_key", ""),
        "douyin_client_secret": form.get("douyin_client_secret", ""),
        "qwen_api_key": form.get("qwen_api_key", ""),
        "deepseek_api_key": form.get("deepseek_api_key", ""),
        "openclaw_url": form.get("openclaw_url", ""),
        "oceanengine_app_id": form.get("oceanengine_app_id", ""),
        "oceanengine_app_secret": form.get("oceanengine_app_secret", ""),
        "oceanengine_advertiser_id": form.get("oceanengine_advertiser_id", ""),
    }
    save_settings(data)
    return RedirectResponse(url="/settings?saved=1", status_code=302)
