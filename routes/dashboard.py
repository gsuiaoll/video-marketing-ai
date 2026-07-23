"""首页仪表盘 — 支持全部/单商家切换"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from database import get_db
from models import Merchant, Script, Video, DouyinAccount, CSMessage, ShootingTask, OceanEngineAccount, ShootingScript, ShootingIP, ShootingMerchant

router = APIRouter(tags=["仪表盘"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


def check_auth(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        from urllib.parse import quote
        from fastapi import HTTPException
        full_path = request.url.path
        if request.url.query:
            full_path += "?" + (request.url.query.decode() if isinstance(request.url.query, bytes) else request.url.query)
        next_url = quote(full_path, safe='/?=&')
        raise HTTPException(status_code=302, headers={"Location": f"/auth/login?next={next_url}"})
    return int(user_id)


def _maybe_filter(q, col, mid):
    return q.filter(col == mid) if mid else q


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    raw = request.query_params.get("merchant_id")
    mid = int(raw) if raw and raw.isdigit() else 0
    today = date.today()

    # 统计
    qm = db.query(Merchant).filter(Merchant.status == "active")
    qs = db.query(Script)
    qv = db.query(Video)
    qd = db.query(DouyinAccount).filter(DouyinAccount.status == "active")
    qcs = db.query(CSMessage).filter(CSMessage.status == "pending")
    qst = db.query(ShootingTask)
    if mid:
        qm = qm.filter(Merchant.id == mid)
        qs = qs.filter(Script.merchant_id == mid)
        qv = qv.filter(Video.merchant_id == mid)
        qd = qd.filter(DouyinAccount.merchant_id == mid)
        qst = qst.filter(ShootingTask.merchant_id == mid)

    total_merchants = qm.count() if not mid else 1
    total_scripts = qs.count()
    starred_scripts = db.query(Script).filter(Script.is_starred == 1) if not mid else qs.filter(Script.is_starred == 1)
    starred_scripts = starred_scripts.count()
    total_videos = qv.count()
    active_douyin = qd.count()
    pending_cs = qcs.count() if not mid else 0  # CS 不按商家分
    recent_scripts = qs.order_by(Script.created_at.desc()).limit(5).all()
    recent_videos = qv.order_by(Video.created_at.desc()).limit(5).all()
    merchants = db.query(Merchant).order_by(Merchant.name).all()
    sel_merchant = db.query(Merchant).filter(Merchant.id == mid).first() if mid else None

    # 趋势
    trend_days, trend_scripts, trend_videos = [], [], []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        trend_days.append(d.strftime("%m/%d"))
        ts = qs.filter(func.date(Script.created_at) == d.strftime("%Y-%m-%d")).count()
        tv = qv.filter(func.date(Video.created_at) == d.strftime("%Y-%m-%d")).count()
        trend_scripts.append(ts)
        trend_videos.append(tv)

    # 本月 vs 上月
    this_month_start = today.replace(day=1)
    last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
    last_month_end = this_month_start - timedelta(days=1)

    def _month_count(base_q, col, d_start, d_end):
        q = base_q.filter(col >= d_start)
        if d_end:
            q = q.filter(col <= d_end)
        return q.count()

    this_month_scripts = _month_count(qs, Script.created_at, this_month_start, None)
    last_month_scripts = _month_count(qs, Script.created_at, last_month_start, last_month_end)
    this_month_videos  = _month_count(qv, Video.created_at, this_month_start, None)
    last_month_videos  = _month_count(qv, Video.created_at, last_month_start, last_month_end)
    this_month_shots   = _month_count(qst, ShootingTask.scheduled_date,
                                       this_month_start.strftime("%Y-%m-%d"), None)
    last_month_shots   = _month_count(qst, ShootingTask.scheduled_date,
                                       last_month_start.strftime("%Y-%m-%d"),
                                       last_month_end.strftime("%Y-%m-%d"))

    # ── Feature 1: 本月 vs 上月实际完成拍摄（status='done'）──
    this_month_done = qst.filter(
        ShootingTask.status == 'done',
        ShootingTask.scheduled_date >= this_month_start.strftime("%Y-%m-%d")
    ).count()
    last_month_done = qst.filter(
        ShootingTask.status == 'done',
        ShootingTask.scheduled_date >= last_month_start.strftime("%Y-%m-%d"),
        ShootingTask.scheduled_date <= last_month_end.strftime("%Y-%m-%d")
    ).count()

    # ── Feature 1: 商家排行 — 本月完成拍摄数 Top 10 ──
    merchant_ranking = db.query(
        ShootingMerchant.name,
        func.count(ShootingTask.id).label('cnt')
    ).join(ShootingTask, ShootingTask.merchant_id == ShootingMerchant.id).filter(
        ShootingTask.status == 'done',
        ShootingTask.scheduled_date >= this_month_start.strftime("%Y-%m-%d")
    ).group_by(ShootingMerchant.id).order_by(desc('cnt')).limit(10).all()

    # ── Feature 1: IP 使用率 — 出镜 IP Top 10 ──
    ip_usage = db.query(
        ShootingIP.name,
        ShootingIP.role,
        func.count(ShootingTask.id).label('cnt')
    ).join(ShootingTask, ShootingTask.ip_id == ShootingIP.id).filter(
        ShootingTask.ip_id.isnot(None)
    ).group_by(ShootingIP.id).order_by(desc('cnt')).limit(10).all()

    # ── Feature 1: 拍摄文案统计 ──
    total_shooting_scripts = db.query(ShootingScript).count()
    ai_scripts = db.query(ShootingScript).filter(ShootingScript.source == 'ai').count()
    manual_scripts = total_shooting_scripts - ai_scripts
    ai_pct = round(ai_scripts / total_shooting_scripts * 100) if total_shooting_scripts > 0 else 0

    # ── Feature 1: 商家画像完善率 ──
    total_active_global = db.query(Merchant).filter(Merchant.status == 'active').count()
    profiled_global = db.query(Merchant).filter(
        Merchant.status == 'active',
        (Merchant.business_model != '') | (Merchant.products_dishes != '')
    ).count()
    profile_pct = round(profiled_global / total_active_global * 100) if total_active_global > 0 else 0

    # 投放消耗
    ad_cost = None
    try:
        from services import oceanengine_service as oe
        today_str = today.strftime("%Y-%m-%d")
        accounts = db.query(OceanEngineAccount).filter(OceanEngineAccount.status == "active")
        if mid:
            accounts = accounts.filter(OceanEngineAccount.merchant_id == mid)
        accounts = accounts.all()
        total_cost = 0.0
        if not accounts:
            token = oe._get_setting("oceanengine_access_token", "")
            aid = oe._get_setting("oceanengine_advertiser_id", "")
            if token and aid:
                r = oe.fetch_report_for_account(today_str, today_str, aid, token)
                total_cost = float(r.get("summary", {}).get("cost", 0))
        else:
            for acc in accounts:
                token = acc.access_token or oe._get_setting("oceanengine_access_token", "")
                if not token:
                    continue
                try:
                    r = oe.fetch_report_for_account(today_str, today_str, acc.advertiser_id, token)
                    total_cost += float(r.get("summary", {}).get("cost", 0))
                except Exception:
                    pass
        ad_cost = total_cost if total_cost > 0 else None
    except Exception:
        pass

    templates = get_templates()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "mid": mid,
        "total_merchants": total_merchants, "total_scripts": total_scripts,
        "starred_scripts": starred_scripts, "total_videos": total_videos,
        "active_douyin": active_douyin, "pending_cs": pending_cs,
        "recent_scripts": recent_scripts, "recent_videos": recent_videos,
        "merchants": merchants, "sel_merchant": sel_merchant,
        "ad_cost": ad_cost,
        "trend_days": trend_days, "trend_scripts": trend_scripts,
        "trend_videos": trend_videos,
        "this_month_scripts": this_month_scripts, "last_month_scripts": last_month_scripts,
        "this_month_videos": this_month_videos, "last_month_videos": last_month_videos,
        "this_month_shots": this_month_shots, "last_month_shots": last_month_shots,
        "this_month_done": this_month_done, "last_month_done": last_month_done,
        "merchant_ranking": merchant_ranking,
        "ip_usage": ip_usage,
        "total_shooting_scripts": total_shooting_scripts,
        "ai_scripts": ai_scripts, "manual_scripts": manual_scripts,
        "ai_pct": ai_pct,
        "total_active_global": total_active_global,
        "profile_pct": profile_pct, "profiled_merchants": profiled_global,
    })
