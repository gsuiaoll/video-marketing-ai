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

    # ── 出镜IP（多表联查：ShootingMerchant名称匹配 → IP层级展示）──
    from models import ShootingIP, ShootingMerchant
    merchant_ip_map = {}       # merchant_id -> [(ip_name, is_primary, parent_name)]
    merchant_shooting = {}     # merchant_id -> {quota, auto_schedule, need_shooting}
    merchant_is_shooting_only = set()  # 仅存在于排班表、不在主商家表的商家ID

    all_ips = db.query(ShootingIP).filter(ShootingIP.status == "active").all()
    ip_name_by_id = {ip.id: ip.name for ip in all_ips}
    sm_ip_map = {}
    for ip in all_ips:
        sm_ip_map.setdefault(ip.merchant_id, []).append(ip)

    shooting_merchants = db.query(ShootingMerchant).filter(ShootingMerchant.status == "active").all()

    for sm in shooting_merchants:
        ips = sm_ip_map.get(sm.id, [])
        primary_ips = [ip for ip in ips if not ip.parent_ip_id]
        secondary_ips = [ip for ip in ips if ip.parent_ip_id]
        ip_list = []
        for ip in primary_ips:
            ip_list.append((ip.name, True, None))
            for sub in secondary_ips:
                if sub.parent_ip_id == ip.id:
                    ip_list.append((sub.name, False, ip.name))
        for sub in secondary_ips:
            if sub.parent_ip_id not in {ip.id for ip in primary_ips}:
                ip_list.append((sub.name, False, ip_name_by_id.get(sub.parent_ip_id, '?')))

        sd = {
            "ips": ip_list,
            "quota": sm.monthly_quota or 25,
            "auto_schedule": sm.auto_schedule or 1,
            "need_shooting": sm.need_shooting if sm.need_shooting is not None else 1,
        }

        # 通过外键 main_merchant_id 直连主商家表
        if sm.main_merchant_id is not None:
            merchant_ip_map[sm.main_merchant_id] = ip_list
            merchant_shooting[sm.main_merchant_id] = sd
        else:
            # 仅存在于排班表（无主商家关联）
            sm_id = sm.id + 10000
            merchant_ip_map[sm_id] = ip_list
            merchant_shooting[sm_id] = sd
            merchant_is_shooting_only.add(sm_id)
            extra = type('ShootingOnly', (), {})()
            extra.id = sm_id
            extra.name = sm.name
            extra.district = sm.district or ""
            extra.industry = ""
            extra.need_shooting = sd["need_shooting"]
            extra.monthly_quota = sd["quota"]
            extra.linked_merchant_id = sm.linked_merchant_id
            extra.products_dishes = ""
            extra.service_features = ""
            extra.business_model = ""
            merchants.append(extra)

    # 主商家按创建时间，仅排班商家追加末尾按名称
    main_only = [m for m in merchants if m.id not in merchant_is_shooting_only]
    extra_only = [m for m in merchants if m.id in merchant_is_shooting_only]
    extra_only.sort(key=lambda m: m.name)
    merchants[:] = main_only + extra_only

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
        "merchant_shooting": merchant_shooting,
        "merchant_is_shooting_only": merchant_is_shooting_only,
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

    from models import OceanEngineAccount, RedBookAccount, ADQAccount, ShootingIP, ShootingMerchant
    ad_accounts = db.query(OceanEngineAccount).filter(
        OceanEngineAccount.merchant_id == merchant_id, OceanEngineAccount.status == "active"
    ).all()
    redbook_accounts = db.query(RedBookAccount).filter(
        RedBookAccount.merchant_id == merchant_id, RedBookAccount.status == "active"
    ).all()
    adq_accounts = db.query(ADQAccount).filter(
        ADQAccount.merchant_id == merchant_id, ADQAccount.status == "active"
    ).all()

    # 出镜IP（通过 ShootingMerchant 名称匹配）
    shooting_merchant = db.query(ShootingMerchant).filter(
        ShootingMerchant.name == merchant.name,
        ShootingMerchant.status == "active"
    ).first()
    merchant_ips = []
    if shooting_merchant:
        merchant_ips = db.query(ShootingIP).filter(
            ShootingIP.merchant_id == shooting_merchant.id,
            ShootingIP.status == "active"
        ).order_by(ShootingIP.name).all()

    templates = get_templates()
    return templates.TemplateResponse("merchant_detail.html", {
        "request": request,
        "merchant": merchant,
        "douyin_accounts": douyin_accounts,
        "ad_accounts": ad_accounts,
        "redbook_accounts": redbook_accounts,
        "adq_accounts": adq_accounts,
        "scripts": scripts,
        "videos": videos,
        "merchant_ips": merchant_ips,
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
