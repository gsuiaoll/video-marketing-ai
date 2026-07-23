"""脚本库 — 所有拍摄文案的集中管理和检索"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import ShootingScript, ShootingTask, ShootingMerchant, ShootingIP

router = APIRouter(prefix="/scripts-library", tags=["脚本库"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("")
def scripts_library(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)

    search = request.query_params.get("search", "").strip()

    query = db.query(ShootingScript).options(
        joinedload(ShootingScript.task).joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingScript.task).joinedload(ShootingTask.ip),
    )

    if search:
        # Join through task -> merchant to filter by merchant name
        query = query.join(
            ShootingTask, ShootingScript.task_id == ShootingTask.id
        ).join(
            ShootingMerchant, ShootingTask.merchant_id == ShootingMerchant.id
        ).filter(
            (ShootingMerchant.name.contains(search)) |
            (ShootingScript.content.contains(search))
        )

    scripts = query.order_by(ShootingScript.created_at.desc()).limit(500).all()

    source_label = {"manual": "✍️手动", "ai": "🤖AI"}

    templates = get_templates()
    return templates.TemplateResponse("scripts_library.html", {
        "request": request,
        "scripts": scripts,
        "search": search,
        "source_label": source_label,
    })


@router.get("/{script_id}/delete")
def delete_script(script_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    s = db.query(ShootingScript).filter(ShootingScript.id == script_id).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse(url="/scripts-library", status_code=302)
