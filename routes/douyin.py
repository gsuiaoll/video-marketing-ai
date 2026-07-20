import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import DouyinAccount, DouyinVideo, WebhookEvent, Merchant
from services.douyin_api import get_auth_url, exchange_code, fetch_user_videos, fetch_video_stats, get_video_jump_url, forward_to_douyin

router = APIRouter(prefix="/douyin", tags=["抖音"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/connect/{merchant_id}")
def start_oauth(merchant_id: int, request: Request):
    """跳转到抖音OAuth授权页"""
    # 使用稳定的回调地址（可用 ngrok 或自己的域名）
    import json
    from pathlib import Path
    settings_file = Path(__file__).parent.parent / "data" / "settings.json"
    site_url = "https://doze-unlatch-refrain.ngrok-free.dev"
    if settings_file.exists():
        try:
            s = json.loads(settings_file.read_text(encoding="utf-8"))
            site_url = s.get("site_url", site_url)
        except Exception:
            pass
    callback_url = site_url.rstrip("/") + "/douyin/callback"
    url = get_auth_url(callback_url, state=str(merchant_id))
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback")
def oauth_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    """抖音OAuth回调"""
    if not code:
        raise HTTPException(status_code=400, detail="授权失败：未收到code")
    merchant_id = int(state) if state else 0
    try:
        token_data = exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"换取Token失败: {e}")

    account = DouyinAccount(
        merchant_id=merchant_id,
        account_name=token_data.get("open_id", "")[:20],
        access_token=token_data.get("access_token", ""),
        refresh_token=token_data.get("refresh_token", ""),
        status="active"
    )
    db.add(account)
    db.commit()
    return RedirectResponse(url=f"/merchants/{merchant_id}", status_code=302)


@router.post("/manual-token/{merchant_id}")
async def manual_token(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    """手动录入 access_token"""
    form = await request.form()
    account = DouyinAccount(
        merchant_id=merchant_id,
        account_name=form.get("account_name", "手动录入"),
        access_token=form.get("access_token", ""),
        refresh_token=form.get("refresh_token", ""),
        status="active"
    )
    db.add(account)
    db.commit()
    return RedirectResponse(url=f"/merchants/{merchant_id}", status_code=302)


# ── Webhook 接收抖音视频事件 ──

@router.post("/webhook/video")
async def douyin_video_webhook(request: Request, db: Session = Depends(get_db)):
    """接收抖音视频发布/更新事件"""
    try:
        body = await request.body()
        payload = json.loads(body)
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    # Webhook 验证：抖音首次配置时发送 verify_webhook 事件
    if payload.get("event") == "verify_webhook":
        challenge = payload.get("content", {}).get("challenge", "")
        if challenge:
            return JSONResponse({"challenge": challenge})

    event_type = payload.get("event", "")
    raw_body_str = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)

    # 统一记录事件日志
    log_entry = WebhookEvent(
        event=event_type,
        from_user_id=payload.get("from_user_id", ""),
        to_user_id=payload.get("to_user_id", ""),
        client_key=payload.get("client_key", ""),
        content=json.dumps(payload.get("content", {}), ensure_ascii=False),
        raw_body=raw_body_str,
    )
    db.add(log_entry)

    # 根据事件类型处理
    if event_type == "create_video":
        # 视频分享事件 → 同步视频数据
        content = payload.get("content", {})
        if isinstance(content, str):
            try: content = json.loads(content)
            except: content = {}
        vid = content.get("item_id", "") or content.get("video_id", "")
        if vid:
            existing = db.query(DouyinVideo).filter(DouyinVideo.video_id == vid).first()
            if not existing:
                dv = DouyinVideo(video_id=vid)
                from_user = payload.get("from_user_id", "")
                acct = db.query(DouyinAccount).filter(
                    DouyinAccount.account_name.like(f"%{from_user}%")
                ).first() if from_user else None
                if acct:
                    dv.douyin_account_id = acct.id
                    dv.merchant_id = acct.merchant_id
                dv.raw_data = raw_body_str
                db.add(dv)
        log_entry.status = "processed"

    elif event_type == "authorize":
        # 用户授权 → 记录
        log_entry.status = "processed"

    elif event_type == "unauthorize":
        # 用户解除授权 → 标记账号失效
        from_user = payload.get("from_user_id", "")
        acct = db.query(DouyinAccount).filter(
            DouyinAccount.account_name.like(f"%{from_user}%")
        ).first() if from_user else None
        if acct:
            acct.status = "revoked"
        log_entry.status = "processed"

    elif event_type == "im_authorize":
        # IM 授权 → 记录
        log_entry.status = "processed"

    elif event_type == "im_auth_code":
        # 站内信授权码 → 记录，可用于换取 token
        log_entry.status = "processed"

    elif event_type in ("contract_authorize", "contract_unauthorize"):
        # 经营关系授权/解除
        log_entry.status = "processed"

    db.commit()

    return JSONResponse({"status": "ok", "event": event_type})


# ── 同步视频管理 ──

@router.get("/webhook-log")
def webhook_log(request: Request, db: Session = Depends(get_db)):
    """Webhook 事件日志"""
    from routes.merchants import check_auth
    check_auth(request)
    events = db.query(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(100).all()
    templates = get_templates()
    return templates.TemplateResponse("douyin_webhook_log.html", {
        "request": request, "events": events,
    })


@router.get("/videos")
def douyin_video_list(request: Request, db: Session = Depends(get_db)):
    """查看 Webhook 同步的抖音视频"""
    from routes.merchants import check_auth
    check_auth(request)
    raw = request.query_params.get("merchant_id")
    mid = int(raw) if raw and raw.isdigit() else 0
    q = db.query(DouyinVideo).order_by(DouyinVideo.created_at.desc())
    if mid:
        q = q.filter(DouyinVideo.merchant_id == mid)
    videos = q.limit(100).all()
    merchants = db.query(Merchant).filter(Merchant.status == "active").order_by(Merchant.name).all()
    templates = get_templates()
    return templates.TemplateResponse("douyin_videos.html", {
        "request": request, "videos": videos, "merchants": merchants, "mid": mid,
    })


@router.get("/videos/sync")
def sync_videos(request: Request, db: Session = Depends(get_db)):
    """从抖音 API 拉取已授权账号的视频列表"""
    from routes.merchants import check_auth
    check_auth(request)
    accounts = db.query(DouyinAccount).filter(DouyinAccount.status == "active").all()
    total_synced = 0
    for acc in accounts:
        if not acc.access_token:
            continue
        videos = fetch_user_videos(acc.access_token, acc.account_name, count=30)
        for v in videos:
            vid = v.get("item_id", "")
            if not vid:
                continue
            existing = db.query(DouyinVideo).filter(DouyinVideo.video_id == vid).first()
            if not existing:
                dv = DouyinVideo(
                    video_id=vid,
                    title=v.get("title", ""),
                    cover_url=v.get("cover", {}).get("url_list", [""])[0] if v.get("cover") else "",
                    share_url=v.get("share_url", ""),
                    duration_ms=v.get("duration", 0),
                    douyin_account_id=acc.id,
                    merchant_id=acc.merchant_id,
                    raw_data=json.dumps(v, ensure_ascii=False),
                )
                db.add(dv)
                total_synced += 1
        # 拉取视频数据（播放量等）
        if videos:
            item_ids = [v.get("item_id") for v in videos if v.get("item_id")]
            if item_ids:
                stats = fetch_video_stats(acc.access_token, acc.account_name, item_ids)
                if isinstance(stats, list):
                    for sv in stats:
                        item_id = sv.get("item_id", "")
                        dv = db.query(DouyinVideo).filter(DouyinVideo.video_id == item_id).first()
                        if dv:
                            stat_data = sv.get("statistics", {})
                            dv.play_count = int(stat_data.get("play_count", 0))
                            dv.like_count = int(stat_data.get("digg_count", 0))
                            dv.comment_count = int(stat_data.get("comment_count", 0))
                            dv.share_count = int(stat_data.get("share_count", 0))
    db.commit()
    mid = request.query_params.get("merchant_id", "")
    redir = f"/douyin/videos?synced={total_synced}"
    if mid:
        redir += f"&merchant_id={mid}"
    return RedirectResponse(url=redir, status_code=302)


@router.get("/videos/{vid}/delete")
def delete_douyin_video(vid: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    v = db.query(DouyinVideo).filter(DouyinVideo.id == vid).first()
    if v:
        db.delete(v)
        db.commit()
    return RedirectResponse(url=_keep_mid(request, "/douyin/videos"), status_code=302)


def _keep_mid(request: Request, base: str) -> str:
    mid = request.query_params.get("merchant_id", "")
    if mid:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}merchant_id={mid}"
    return base


@router.get("/videos/{vid}/jump")
def jump_to_douyin(vid: int, request: Request, db: Session = Depends(get_db)):
    """获取抖音跳转链接并跳转"""
    from routes.merchants import check_auth
    check_auth(request)
    v = db.query(DouyinVideo).filter(DouyinVideo.id == vid).first()
    if not v or not v.douyin_account_id:
        return RedirectResponse(url=_keep_mid(request, "/douyin/videos"), status_code=302)
    account = db.query(DouyinAccount).filter(DouyinAccount.id == v.douyin_account_id).first()
    if not account or not account.access_token:
        return RedirectResponse(url=_keep_mid(request, "/douyin/videos"), status_code=302)
    jump_url = get_video_jump_url(account.access_token, account.account_name, v.video_id)
    if jump_url:
        return RedirectResponse(url=jump_url, status_code=302)
    if v.share_url:
        return RedirectResponse(url=v.share_url, status_code=302)
    return RedirectResponse(url=_keep_mid(request, "/douyin/videos"), status_code=302)


@router.get("/videos/{vid}/forward")
def forward_video(vid: int, request: Request, db: Session = Depends(get_db)):
    """转发视频到抖音以日常作品发布"""
    from routes.merchants import check_auth
    check_auth(request)
    v = db.query(DouyinVideo).filter(DouyinVideo.id == vid).first()
    if not v or not v.douyin_account_id:
        return RedirectResponse(url=_keep_mid(request, "/douyin/videos"), status_code=302)
    account = db.query(DouyinAccount).filter(DouyinAccount.id == v.douyin_account_id).first()
    if not account or not account.access_token:
        return RedirectResponse(url=_keep_mid(request, "/douyin/videos"), status_code=302)
    result = forward_to_douyin(account.access_token, account.account_name, v.video_id)
    return RedirectResponse(url="/douyin/videos?forwarded=1", status_code=302)


@router.get("/delete/{account_id}")
def delete_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    """删除抖音账号"""
    from routes.merchants import check_auth
    check_auth(request)
    account = db.query(DouyinAccount).filter(DouyinAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404)
    mid = account.merchant_id
    db.delete(account)
    db.commit()
    return RedirectResponse(url=f"/merchants/{mid}", status_code=302)
