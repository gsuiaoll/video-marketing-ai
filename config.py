import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"

# 密钥：生产环境必须换掉，放到环境变量
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

# AI — DeepSeek (兼容 OpenAI SDK)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 兼容旧变量名
QWEN_API_KEY = os.getenv("QWEN_API_KEY", DEEPSEEK_API_KEY)
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", DEEPSEEK_BASE_URL)
QWEN_MODEL = os.getenv("QWEN_MODEL", DEEPSEEK_MODEL)

# 抖音开放平台
DOUYIN_CLIENT_KEY = os.getenv("DOUYIN_CLIENT_KEY", "")
DOUYIN_CLIENT_SECRET = os.getenv("DOUYIN_CLIENT_SECRET", "")

# 视频上传
VIDEO_UPLOAD_DIR = DATA_DIR / "videos"
MAX_UPLOAD_SIZE_MB = 500
