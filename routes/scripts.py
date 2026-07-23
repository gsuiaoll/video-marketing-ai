import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Script
from services.ai_script import generate_script
from routes.merchants import check_auth

router = APIRouter(prefix="/scripts", tags=["脚本"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("")
def list_scripts(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    mid = request.query_params.get("merchant_id", "")
    if mid:
        return RedirectResponse(url=f"/schedule?tab=scripts&merchant_id={mid}", status_code=302)
    return RedirectResponse(url="/schedule?tab=scripts", status_code=302)


@router.get("/generate")
def generate_page(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    return RedirectResponse(url="/schedule?tab=scripts", status_code=302)


@router.post("/generate")
async def do_generate(request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    from models import Merchant
    merchants = db.query(Merchant).all()
    templates = get_templates()

    form = await request.form()
    merchant_id = int(form.get("merchant_id", 0))
    product_info = form.get("product_info", "")
    platform = form.get("platform", "douyin")
    duration = int(form.get("duration_sec", 60))
    extra = form.get("extra_requirements", "")

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        return templates.TemplateResponse("script_generate.html", {
            "request": request, "merchants": merchants,
            "result": None, "error": "请选择商家"
        })

    # 获取所有标星脚本作为经验注入
    starred = db.query(Script).filter(Script.is_starred == 1).order_by(Script.created_at.desc()).limit(5).all()
    starred_examples = []
    for s in starred:
        try:
            starred_examples.append(json.loads(s.content))
        except Exception:
            pass

    # 构建商家画像上下文
    merchant_profile = {
        "products_dishes": merchant.products_dishes or "",
        "recent_updates": merchant.recent_updates or "",
        "business_model": merchant.business_model or "",
        "service_features": merchant.service_features or "",
        "target_customers": merchant.target_customers or "",
        "competitive_advantages": merchant.competitive_advantages or "",
        "promotions": merchant.promotions or "",
        "shooting_notes": merchant.shooting_notes or "",
    }

    try:
        result = generate_script(
            merchant_name=merchant.name,
            industry=merchant.industry or "通用",
            product_info=product_info,
            platform=platform,
            duration_sec=duration,
            extra_requirements=extra,
            starred_examples=starred_examples if starred_examples else None,
            merchant_profile=merchant_profile,
        )

        # 存库
        script = Script(
            merchant_id=merchant.id,
            title=result.get("title", "未命名脚本"),
            platform=platform,
            content=json.dumps(result, ensure_ascii=False),
            ai_generated=1
        )
        db.add(script)
        db.commit()

        return templates.TemplateResponse("script_generate.html", {
            "request": request, "merchants": merchants,
            "result": result, "error": "", "script_id": script.id
        })
    except Exception as e:
        return templates.TemplateResponse("script_generate.html", {
            "request": request, "merchants": merchants,
            "result": None, "error": str(e)
        })


@router.get("/{script_id}")
def script_detail(script_id: int, request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404)

    content = json.loads(script.content) if script.content else {}
    templates = get_templates()
    return templates.TemplateResponse("script_detail.html", {
        "request": request,
        "script": script,
        "content": content
    })


@router.get("/{script_id}/star")
def toggle_star(script_id: int, request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    script = db.query(Script).filter(Script.id == script_id).first()
    if script:
        script.is_starred = 1 if script.is_starred == 0 else 0
        db.commit()
    return RedirectResponse(url="/scripts", status_code=302)


@router.get("/{script_id}/delete")
def delete_script(script_id: int, request: Request, db: Session = Depends(get_db)):
    check_auth(request)
    script = db.query(Script).filter(Script.id == script_id).first()
    if script:
        db.delete(script)
        db.commit()
    return RedirectResponse(url="/scripts", status_code=302)
