from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Merchant, DouyinAccount, Script, Video, RedBookAccount, ADQAccount

router = APIRouter(prefix="/merchants", tags=["商家"])


def check_auth(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        from urllib.parse import quote
        full_path = request.url.path
        if request.url.query:
            full_path += "?" + request.url.query.decode() if isinstance(request.url.query, bytes) else request.url.query
        next_url = quote(full_path, safe='/?=&')
        raise HTTPException(status_code=302, headers={"Location": f"/auth/login?next={next_url}"})
    return int(user_id)


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("")
def list_merchants(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    merchants = db.query(Merchant).order_by(Merchant.created_at.desc()).all()
    # 构建子商家列表（用于层级展示）
    children_map = {}
    for m in merchants:
        if m.linked_merchant_id:
            children_map.setdefault(m.linked_merchant_id, []).append(m)

    # ── 出镜IP（通过 ShootingMerchant 名称匹配）──
    from models import ShootingIP, ShootingMerchant
    merchant_ip_map = {}  # merchant_id -> [ip_names]
    all_ips = db.query(ShootingIP).filter(ShootingIP.status == "active").all()
    # 构建 ShootingMerchant name -> ip list
    sm_ip_map = {}
    for ip in all_ips:
        sm_ip_map.setdefault(ip.merchant_id, []).append(ip.name)
    # 查询 ShootingMerchant，按名称匹配到 Merchant
    shooting_merchants = db.query(ShootingMerchant).filter(ShootingMerchant.status == "active").all()
    sm_name_to_ips = {}
    for sm in shooting_merchants:
        if sm.id in sm_ip_map:
            sm_name_to_ips[sm.name] = sm_ip_map[sm.id]
    for m in merchants:
        if m.name in sm_name_to_ips:
            merchant_ip_map[m.id] = sm_name_to_ips[m.name]

    # ── 短视频平台账号 (douyin + redbook) ──
    from models import DouyinAccount, RedBookAccount
    merchant_platforms = {}  # merchant_id -> [("抖音", count), ("小红书", count)]
    for m in merchants:
        platforms = []
        dy_count = db.query(DouyinAccount).filter(
            DouyinAccount.merchant_id == m.id, DouyinAccount.status == "active"
        ).count()
        if dy_count > 0:
            platforms.append(("🎵抖音", dy_count))
        rb_count = db.query(RedBookAccount).filter(
            RedBookAccount.merchant_id == m.id, RedBookAccount.status == "active"
        ).count()
        if rb_count > 0:
            platforms.append(("📕小红书", rb_count))
        if platforms:
            merchant_platforms[m.id] = platforms

    # ── 投流平台账号 (oceanengine + adq) ──
    from models import OceanEngineAccount, ADQAccount
    merchant_ads = {}  # merchant_id -> [("巨量引擎", count), ("ADQ", count)]
    for m in merchants:
        ads = []
        oe_count = db.query(OceanEngineAccount).filter(
            OceanEngineAccount.merchant_id == m.id, OceanEngineAccount.status == "active"
        ).count()
        if oe_count > 0:
            ads.append(("📊巨量引擎", oe_count))
        adq_count = db.query(ADQAccount).filter(
            ADQAccount.merchant_id == m.id, ADQAccount.status == "active"
        ).count()
        if adq_count > 0:
            ads.append(("💼ADQ", adq_count))
        if ads:
            merchant_ads[m.id] = ads

    templates = get_templates()
    return templates.TemplateResponse("merchants.html", {
        "request": request,
        "merchants": merchants,
        "children_map": children_map,
        "merchant_ip_map": merchant_ip_map,
        "merchant_platforms": merchant_platforms,
        "merchant_ads": merchant_ads,
    })


@router.get("/new")
def new_merchant_page(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    all_merchants = db.query(Merchant).filter(Merchant.status == "active").order_by(Merchant.name).all()
    templates = get_templates()
    return templates.TemplateResponse("merchant_form.html", {
        "request": request, "merchant": None, "error": "",
        "all_merchants": all_merchants,
    })


@router.post("/new")
async def create_merchant(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    form = await request.form()
    merchant = Merchant(
        name=form.get("name", ""),
        industry=form.get("industry", ""),
        contact_name=form.get("contact_name", ""),
        contact_phone=form.get("contact_phone", ""),
        address=form.get("address", ""),
        district=form.get("district", ""),
        monthly_quota=int(form.get("monthly_quota", "25")),
        products_dishes=form.get("products_dishes", ""),
        recent_updates=form.get("recent_updates", ""),
        business_model=form.get("business_model", ""),
        service_features=form.get("service_features", ""),
        target_customers=form.get("target_customers", ""),
        competitive_advantages=form.get("competitive_advantages", ""),
        promotions=form.get("promotions", ""),
        shooting_notes=form.get("shooting_notes", ""),
    )
    merchant.need_shooting = 1 if form.get("need_shooting", "1") == "1" else 0
    linked_raw = form.get("linked_merchant_id", "")
    if linked_raw and linked_raw.isdigit():
        merchant.linked_merchant_id = int(linked_raw)
    db.add(merchant)
    db.commit()
    return RedirectResponse(url="/merchants", status_code=302)


@router.get("/{merchant_id}")
def merchant_detail(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")

    douyin_accounts = db.query(DouyinAccount).filter(
        DouyinAccount.merchant_id == merchant_id
    ).all()

    scripts = db.query(Script).filter(Script.merchant_id == merchant_id).order_by(
        Script.created_at.desc()
    ).all()

    videos = db.query(Video).filter(Video.merchant_id == merchant_id).order_by(
        Video.created_at.desc()
    ).all()

    from models import OceanEngineAccount, RedBookAccount, ADQAccount
    ad_accounts = db.query(OceanEngineAccount).filter(
        OceanEngineAccount.merchant_id == merchant_id, OceanEngineAccount.status == "active"
    ).all()
    redbook_accounts = db.query(RedBookAccount).filter(
        RedBookAccount.merchant_id == merchant_id, RedBookAccount.status == "active"
    ).all()
    adq_accounts = db.query(ADQAccount).filter(
        ADQAccount.merchant_id == merchant_id, ADQAccount.status == "active"
    ).all()

    templates = get_templates()
    return templates.TemplateResponse("merchant_detail.html", {
        "request": request,
        "merchant": merchant,
        "douyin_accounts": douyin_accounts,
        "ad_accounts": ad_accounts,
        "redbook_accounts": redbook_accounts,
        "adq_accounts": adq_accounts,
        "scripts": scripts,
        "videos": videos
    })


# ── 多平台账号管理（通用）──

PLATFORM_MODELS = {
    "douyin": (DouyinAccount, {"account_name": "account_name", "access_token": "access_token", "refresh_token": "refresh_token"}),
    "redbook": (RedBookAccount, {"account_name": "account_name", "user_id": "user_id", "access_token": "access_token", "refresh_token": "refresh_token"}),
    "adq": (ADQAccount, {"account_name": "account_name", "advertiser_id": "advertiser_id", "access_token": "access_token", "refresh_token": "refresh_token"}),
}


@router.post("/{merchant_id}/link-platform")
async def link_platform_account(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    """给商家关联一个平台账号"""
    check_auth(request)
    form = await request.form()
    platform = form.get("platform", "")
    if platform not in PLATFORM_MODELS:
        return RedirectResponse(url=f"/merchants/{merchant_id}", status_code=302)

    Model, field_map = PLATFORM_MODELS[platform]
    kwargs = {"merchant_id": merchant_id}
    for attr, form_key in field_map.items():
        kwargs[attr] = form.get(form_key, "").strip()
    if platform == "adq" and not kwargs.get("advertiser_id"):
        return RedirectResponse(url=f"/merchants/{merchant_id}", status_code=302)

    db.add(Model(**kwargs))
    db.commit()
    return RedirectResponse(url=f"/merchants/{merchant_id}", status_code=302)


@router.get("/platform-account/{account_id}/delete")
def delete_platform_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    """删除平台账号"""
    check_auth(request)
    platform = request.query_params.get("platform", "")
    if platform not in PLATFORM_MODELS:
        return RedirectResponse(url="/merchants", status_code=302)
    Model, _ = PLATFORM_MODELS[platform]
    acc = db.query(Model).filter(Model.id == account_id).first()
    if acc:
        acc.status = "inactive"
        db.commit()
    return RedirectResponse(url=f"/merchants/{acc.merchant_id}" if acc else "/merchants", status_code=302)


@router.get("/{merchant_id}/edit")
def edit_merchant_page(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    """编辑商家页面"""
    check_auth(request)
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    all_merchants = db.query(Merchant).filter(Merchant.status == "active", Merchant.id != merchant_id).order_by(Merchant.name).all()
    templates = get_templates()
    return templates.TemplateResponse("merchant_form.html", {
        "request": request, "merchant": merchant, "error": "",
        "all_merchants": all_merchants,
    })


@router.post("/{merchant_id}/edit")
async def update_merchant(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    """保存编辑"""
    check_auth(request)
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    form = await request.form()
    merchant.name = form.get("name", merchant.name)
    merchant.industry = form.get("industry", merchant.industry)
    merchant.contact_name = form.get("contact_name", merchant.contact_name)
    merchant.contact_phone = form.get("contact_phone", merchant.contact_phone)
    merchant.address = form.get("address", merchant.address)
    merchant.district = form.get("district", merchant.district)
    merchant.monthly_quota = int(form.get("monthly_quota", str(merchant.monthly_quota or 25)))
    merchant.products_dishes = form.get("products_dishes", merchant.products_dishes)
    merchant.recent_updates = form.get("recent_updates", merchant.recent_updates)
    merchant.business_model = form.get("business_model", merchant.business_model)
    merchant.service_features = form.get("service_features", merchant.service_features)
    merchant.target_customers = form.get("target_customers", merchant.target_customers)
    merchant.competitive_advantages = form.get("competitive_advantages", merchant.competitive_advantages)
    merchant.promotions = form.get("promotions", merchant.promotions)
    merchant.shooting_notes = form.get("shooting_notes", merchant.shooting_notes)
    merchant.need_shooting = 1 if form.get("need_shooting", "1") == "1" else 0
    linked_raw = form.get("linked_merchant_id", "")
    merchant.linked_merchant_id = int(linked_raw) if linked_raw and linked_raw.isdigit() else None
    db.commit()
    return RedirectResponse(url=f"/merchants/{merchant_id}", status_code=302)


@router.get("/{merchant_id}/delete")
def delete_merchant(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    """删除商家（级联删除关联的抖音账号、脚本、视频）"""
    check_auth(request)
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    # 级联删除关联数据
    db.query(DouyinAccount).filter(DouyinAccount.merchant_id == merchant_id).delete()
    db.query(Script).filter(Script.merchant_id == merchant_id).delete()
    db.query(Video).filter(Video.merchant_id == merchant_id).delete()
    db.delete(merchant)
    db.commit()
    return RedirectResponse(url="/merchants", status_code=302)
