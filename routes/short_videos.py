"""统一短视频管理 — 多平台视频聚合页面"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Merchant, Video, DouyinVideo, DouyinAccount, RedBookAccount

router = APIRouter(prefix="/short-videos", tags=["短视频"])

PLATFORMS = [
    {"key": "douyin", "name": "🎵 抖音", "color": "#fe2c55"},
    {"key": "redbook", "name": "📕 小红书", "color": "#ff2442"},
    {"key": "shipinhao", "name": "📺 视频号", "color": "#07c160"},
    {"key": "tiktok", "name": "🌍 TikTok", "color": "#000"},
    {"key": "facebook", "name": "📘 Facebook", "color": "#1877f2"},
]


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("")
def short_videos_home(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)

    platform = request.query_params.get("platform", "douyin")
    raw_mid = request.query_params.get("merchant_id")
    mid = int(raw_mid) if raw_mid and raw_mid.isdigit() else 0

    merchants = db.query(Merchant).filter(Merchant.status == "active").order_by(Merchant.name).all()

    # ── 抖音：合并 webhook 同步视频 + 本地上传视频 ──
    douyin_videos = []
    douyin_accounts = []
    if platform == "douyin":
        q = db.query(DouyinVideo).order_by(DouyinVideo.created_at.desc())
        if mid:
            q = q.filter(DouyinVideo.merchant_id == mid)
        douyin_videos = q.limit(100).all()

        aq = db.query(DouyinAccount).filter(DouyinAccount.status == "active")
        if mid:
            aq = aq.filter(DouyinAccount.merchant_id == mid)
        douyin_accounts = aq.all()

    # ── 本地上传视频 ──
    local_q = db.query(Video).order_by(Video.created_at.desc())
    if platform == "douyin":
        local_q = local_q.filter(Video.platform == "douyin")
    elif platform != "douyin":
        local_q = local_q.filter(Video.platform == platform)
    if mid:
        local_q = local_q.filter(Video.merchant_id == mid)
    local_videos = local_q.limit(100).all()

    templates = get_templates()
    return templates.TemplateResponse("short_videos.html", {
        "request": request,
        "platforms": PLATFORMS,
        "current_platform": platform,
        "merchants": merchants,
        "mid": mid,
        "douyin_videos": douyin_videos,
        "douyin_accounts": douyin_accounts,
        "local_videos": local_videos,
    })
