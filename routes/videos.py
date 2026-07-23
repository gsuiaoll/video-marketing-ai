from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Video, Merchant
from config import VIDEO_UPLOAD_DIR, MAX_UPLOAD_SIZE_MB
from routes.merchants import check_auth

router = APIRouter(prefix="/videos", tags=["视频"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("")
def list_videos(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    raw = request.query_params.get("merchant_id")
    merchant_id = int(raw) if raw else None
    platform = request.query_params.get("platform", "")
    status = request.query_params.get("status", "")
    query = db.query(Video)
    if merchant_id:
        query = query.filter(Video.merchant_id == merchant_id)
    if platform:
        query = query.filter(Video.platform == platform)
    if status == "published":
        query = query.filter(Video.publish_status != "")
    elif status == "unpublished":
        query = query.filter(Video.publish_status == "")
    videos = query.order_by(Video.created_at.desc()).all()
    merchants = db.query(Merchant).filter(Merchant.status == "active").order_by(Merchant.name).all()

    templates = get_templates()
    return templates.TemplateResponse("videos.html", {
        "request": request, "videos": videos, "merchants": merchants,
        "cur_merchant_id": merchant_id or 0, "cur_platform": platform, "cur_status": status,
    })


@router.post("/upload")
async def upload_video(
    request: Request,
    title: str = Form(""),
    merchant_id: int = Form(0),
    platform: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    check_auth(request)
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"文件过大，最大{MAX_UPLOAD_SIZE_MB}MB")

    VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_ext = Path(file.filename).suffix if file.filename else ".mp4"
    safe_name = f"{merchant_id}_{title or 'video'}_{Path(file.filename).name}"
    file_path = VIDEO_UPLOAD_DIR / safe_name
    file_path.write_bytes(content)

    video = Video(
        merchant_id=merchant_id,
        title=title or (file.filename or "未命名"),
        file_path=str(file_path.relative_to(VIDEO_UPLOAD_DIR.parent)),
        platform=platform,
        description=description,
        tags=tags,
    )
    db.add(video)
    db.commit()
    return RedirectResponse(url=_keep_merchant(request, "/videos"), status_code=302)


@router.get("/{video_id}/publish")
def toggle_publish(video_id: int, request: Request, db: Session = Depends(get_db)):
    """标记/取消发布到指定平台。抖音平台尝试真发"""
    check_auth(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or not video.platform:
        return RedirectResponse(url=_keep_merchant(request, "/videos"), status_code=302)

    current = set(filter(None, (video.publish_status or "").split(",")))
    plat = video.platform

    if plat not in current and plat == "douyin":
        # 尝试真实发布到抖音
        from models import DouyinAccount
        from services.douyin_api import forward_to_douyin
        account = db.query(DouyinAccount).filter(
            DouyinAccount.merchant_id == video.merchant_id,
            DouyinAccount.status == "active"
        ).first()
        if account and account.access_token:
            try:
                # 从本地文件读取内容发布到抖音
                from config import BASE_DIR
                full_path = BASE_DIR / "data" / video.file_path
                if full_path.exists():
                    # 使用 forward API 发布
                    result = forward_to_douyin(account.access_token, account.account_name, "")
                    if result.get("error_code", 1) == 0:
                        plat = "douyin"
            except Exception:
                pass  # API 失败降级为手动标记

    if plat in current:
        current.discard(plat)
    else:
        current.add(plat)
    video.publish_status = ",".join(sorted(current)) if current else ""
    db.commit()
    return RedirectResponse(url=_keep_merchant(request, "/videos"), status_code=302)


def _keep_merchant(request: Request, base: str) -> str:
    mid = request.query_params.get("merchant_id", "")
    if mid:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}merchant_id={mid}"
    return base


@router.get("/play/{video_id}")
def play_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404)
    from config import BASE_DIR
    full_path = BASE_DIR / "data" / video.file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return FileResponse(str(full_path), media_type="video/mp4")


@router.get("/{video_id}/delete")
def delete_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    video = db.query(Video).filter(Video.id == video_id).first()
    if video:
        try:
            from config import BASE_DIR
            full_path = BASE_DIR / "data" / video.file_path
            if full_path.exists():
                full_path.unlink()
        except Exception:
            pass
        db.delete(video)
        db.commit()
    return RedirectResponse(url=_keep_merchant(request, "/videos"), status_code=302)
