"""排班路由共享工具"""
from fastapi import Request


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


def redirect_back(request: Request, path: str = "/schedule") -> str:
    """保留摄影师筛选参数的重定向"""
    pid = request.query_params.get("photographer_id", "")
    if pid:
        sep = "&" if "?" in path else "?"
        return f"{path}{sep}photographer_id={pid}"
    return path
