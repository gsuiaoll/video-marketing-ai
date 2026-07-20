import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User

router = APIRouter(prefix="/auth", tags=["认证"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/login")
def login_page(request: Request):
    templates = get_templates()
    next_url = request.query_params.get("next", "")
    return templates.TemplateResponse("login.html", {"request": request, "error": "", "next": next_url})


@router.post("/login")
async def login(request: Request):
    templates = get_templates()
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    db = next(get_db())
    user = db.query(User).filter(User.username == username).first()

    if not user or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "用户名或密码错误",
            "next": form.get("next", "")
        })

    next_url = form.get("next", "") or "/dashboard"
    resp = RedirectResponse(url=next_url, status_code=302)
    resp.set_cookie(key="user_id", value=str(user.id))
    resp.set_cookie(key="user_role", value=user.role)
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/auth/login", status_code=302)
    resp.delete_cookie("user_id")
    resp.delete_cookie("user_role")
    return resp
