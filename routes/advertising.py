"""巨量引擎广告投放路由 — 多商家、多账户管理"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Merchant, OceanEngineAccount, ADQAccount
from services import oceanengine_service as oe

router = APIRouter(prefix="/advertising", tags=["投放"])


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


def _fetch_all_accounts(start_date: str, end_date: str, db: Session) -> list[dict]:
    """拉取所有已关联的广告账户数据"""
    accounts = db.query(OceanEngineAccount).filter(OceanEngineAccount.status == "active").all()
    if not accounts:
        # Fallback to global advertiser_id
        global_aid = oe._get_setting("oceanengine_advertiser_id", "")
        global_token = oe._get_setting("oceanengine_access_token", "")
        if global_aid and global_token:
            accounts = [type('_', (), {
                'id': 0, 'advertiser_id': global_aid, 'account_name': '主账户',
                'merchant_id': None, 'merchant': None,
                'access_token': global_token, 'refresh_token': oe._get_setting("oceanengine_refresh_token", ""),
            })()]

    results = []
    for acc in accounts:
        try:
            token = acc.access_token or oe._get_setting("oceanengine_access_token", "")
            report = oe.fetch_report_for_account(start_date, end_date, acc.advertiser_id, token)
            if report and report.get("summary"):
                results.append({
                    "account_id": acc.id,
                    "advertiser_id": acc.advertiser_id,
                    "account_name": acc.account_name or f"账户{acc.advertiser_id}",
                    "merchant_name": acc.merchant.name if hasattr(acc, 'merchant') and acc.merchant else "-",
                    "merchant_id": acc.merchant_id if hasattr(acc, 'merchant_id') else None,
                    **report,
                })
        except Exception:
            pass
    return results


@router.get("")
def advertising_dashboard(request: Request, db: Session = Depends(get_db)):
    """广告投放数据看板"""
    check_auth(request)
    today = date.today()

    days_param = request.query_params.get("days", "7")
    days = int(days_param) if days_param.isdigit() else 7
    start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    custom_start = request.query_params.get("start", "")
    custom_end = request.query_params.get("end", "")
    if custom_start and custom_end:
        start_date = custom_start
        end_date = custom_end

    # 获取已关联的广告账户（巨量引擎 + ADQ）
    ocean_accs = db.query(OceanEngineAccount).filter(OceanEngineAccount.status == "active").all()
    adq_accs = db.query(ADQAccount).filter(ADQAccount.status == "active").all()
    linked_accounts = list(ocean_accs) + list(adq_accs)

    # 已配置 = 有巨量引擎凭证，或有任何已关联账户
    has_linked = len(linked_accounts) > 0
    global_configured = bool(oe._get_setting("oceanengine_app_id", ""))
    configured = has_linked or (global_configured and bool(oe._get_setting("oceanengine_advertiser_id", "")))

    error = None
    results = []

    if configured:
        try:
            results = _fetch_all_accounts(start_date, end_date, db)
            if not results:
                error = "未获取到投放数据，请检查账户授权是否有效"
        except Exception as e:
            error = f"数据获取失败: {e}"

    # Aggregate
    agg = {"cost": 0.0, "show": 0, "click": 0, "convert": 0}
    for r in results:
        s = r.get("summary", {})
        agg["cost"] += float(s.get("cost", 0) or 0)
        agg["show"] += int(s.get("show", 0) or 0)
        agg["click"] += int(s.get("click", 0) or 0)
        agg["convert"] += int(s.get("convert", 0) or 0)

    merchants = db.query(Merchant).filter(Merchant.status == "active").order_by(Merchant.name).all()

    templates = get_templates()
    return templates.TemplateResponse("advertising.html", {
        "request": request,
        "configured": configured,
        "has_linked": has_linked,
        "linked_accounts": linked_accounts,
        "ocean_accs": ocean_accs,
        "adq_accs": adq_accs,
        "error": error,
        "results": results,
        "agg": agg,
        "merchants": merchants,
        "days": days,
        "start_date": custom_start or start_date,
        "end_date": custom_end or end_date,
        "today": today.strftime("%Y-%m-%d"),
    })


@router.post("/link")
async def link_account(request: Request, db: Session = Depends(get_db)):
    """关联广告账户到商家"""
    check_auth(request)
    form = await request.form()
    merchant_id = int(form.get("merchant_id", 0))
    advertiser_id = form.get("advertiser_id", "").strip()
    account_name = form.get("account_name", "").strip()
    access_token = form.get("access_token", "").strip()
    refresh_token = form.get("refresh_token", "").strip()

    if not merchant_id or not advertiser_id:
        return RedirectResponse(url="/advertising?error=missing_fields", status_code=302)

    exists = db.query(OceanEngineAccount).filter(
        OceanEngineAccount.merchant_id == merchant_id,
        OceanEngineAccount.advertiser_id == advertiser_id
    ).first()
    if exists:
        exists.account_name = account_name or exists.account_name
        if access_token:
            exists.access_token = access_token
            exists.refresh_token = refresh_token
    else:
        db.add(OceanEngineAccount(
            merchant_id=merchant_id,
            advertiser_id=advertiser_id,
            account_name=account_name or f"账户{advertiser_id}",
            access_token=access_token or oe._get_setting("oceanengine_access_token", ""),
            refresh_token=refresh_token or oe._get_setting("oceanengine_refresh_token", ""),
        ))
    db.commit()
    return RedirectResponse(url="/advertising", status_code=302)


@router.get("/unlink/{account_id}")
def unlink_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    """解除广告账户关联"""
    check_auth(request)
    acc = db.query(OceanEngineAccount).filter(OceanEngineAccount.id == account_id).first()
    if acc:
        acc.status = "inactive"
        db.commit()
    return RedirectResponse(url="/advertising", status_code=302)


@router.get("/authorize")
def authorize(request: Request):
    """生成巨量引擎授权链接并跳转（全局授权）"""
    check_auth(request)
    app_id = oe._get_setting("oceanengine_app_id", "").strip()
    if not app_id:
        return RedirectResponse(url="/settings?error=oceanengine_no_app_id", status_code=302)
    callback_url = str(request.base_url).rstrip("/") + "/advertising/callback"
    auth_url = oe.get_auth_url(app_id, callback_url)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback")
def callback(request: Request):
    """巨量引擎 OAuth 回调"""
    check_auth(request)
    auth_code = request.query_params.get("auth_code", "")
    if not auth_code:
        return RedirectResponse(url="/settings?error=oceanengine_auth_failed", status_code=302)
    app_id = oe._get_setting("oceanengine_app_id", "").strip()
    app_secret = oe._get_setting("oceanengine_app_secret", "").strip()
    try:
        oe.exchange_token(app_id, app_secret, auth_code)
        return RedirectResponse(url="/advertising", status_code=302)
    except Exception:
        return RedirectResponse(url="/settings?error=oceanengine_token_failed", status_code=302)


@router.get("/refresh")
def manual_refresh(request: Request, db: Session = Depends(get_db)):
    """手动刷新所有账户 token"""
    check_auth(request)
    for acc in db.query(OceanEngineAccount).filter(OceanEngineAccount.status == "active").all():
        if acc.refresh_token:
            try:
                new_token = oe.refresh_account_token(acc.advertiser_id, acc.refresh_token)
                if new_token:
                    acc.access_token = new_token
            except Exception:
                pass
    db.commit()
    return RedirectResponse(url="/advertising", status_code=302)
