# 🎬 短视频AI营销系统

本地生活商家短视频代运营一站式管理平台。覆盖账号管理、AI 脚本生成、拍摄排班、投流监控、AI 客服全链路。

## 功能模块

### 🏪 商家管理
- 主商家库 + 总分厂层级关联 + 配额共享
- 8 字段商家画像（菜品/业务模式/目标客户等），注入 AI 脚本生成
- 行业二级分类选择（100+细分选项）
- 多平台账号关联（抖音/小红书/ADQ腾讯广告/巨量引擎）

### 📅 拍摄排班
- 月历视图，AM/PM/全天三行显示
- 智能排班算法：远途全天/近途半天，按摄影师数量自动分配
- 手动排班锁定 + 生成时自动填空
- 临时加拍 / 取消排班（带原因记录）
- 每日自动日期更新 + 过期归档
- 出镜 IP 人物配额管理
- 屏蔽时段设置

### ✍️ AI 文案生成
- DeepSeek API 驱动，结构化脚本输出（钩子/分镜/CTA/标签）
- 商家画像自动注入 prompt
- 标星脚本作为 few-shot 参考

### 📊 投放看板
- 巨量引擎 Marketing API 对接（OAuth 授权 + Token 自动刷新）
- ADQ 腾讯广告多账户管理
- 消耗/展示/点击/转化数据汇总
- CSS 漏斗图 + 账户明细表
- 工作台今日投放消耗卡片

### 📞 客服系统
- 抖音 Webhook 接收私信 → AI 自动回复（DeepSeek）
- 微信客服消息渠道
- 收件箱渠道筛选 + 批量处理
- Mock 降级模式（无 API Key 时关键词匹配）

### 🎥 视频管理
- 上传/标签/描述/目标平台
- 发布状态追踪（已发布/未发布）
- 多平台筛选（抖音/视频号/TikTok）
- 抖音视频 Webhook 自动同步

### 📈 工作台
- 全部/单商家筛选
- 近 7 天趋势柱状图（文案+视频）
- 本月 vs 上月环比
- 快捷操作入口

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3 + FastAPI |
| 数据库 | SQLite + SQLAlchemy |
| 前端 | Jinja2 模板 + Alpine.js + 原生 JS |
| CSS | 手写响应式 |
| AI | DeepSeek API（兼容 OpenAI 格式） |
| 部署 | 阿里云 ECS + Nginx 反代 |

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 浏览器打开
http://localhost:8000
```

默认账号：`admin` / `admin123`

## 配置

进入 `⚙️设置` 页面配置：
- **DeepSeek API Key** — AI 文案生成 & 客服回复
- **抖音 Client Key/Secret** — OAuth 登录 & Webhook
- **巨量引擎 App ID/Secret** — 投放数据拉取

所有配置保存在 `data/settings.json`，无需重启立即生效。

## 项目结构

```
video_marketing_app/
├── main.py              # 入口
├── models.py            # 数据模型
├── database.py          # 数据库初始化 & 迁移
├── config.py            # 配置常量
├── routes/              # 路由层
│   ├── auth.py          # 登录认证
│   ├── dashboard.py     # 工作台
│   ├── merchants.py     # 商家管理
│   ├── schedule.py      # 拍摄排班
│   ├── scripts.py       # AI文案
│   ├── videos.py        # 视频管理
│   ├── advertising.py   # 投放看板
│   ├── douyin.py        # 抖音 OAuth & Webhook
│   ├── cs.py            # 客服系统
│   └── settings.py      # 系统设置
├── services/            # 服务层
│   ├── scheduler.py     # 排班算法
│   ├── ai_script.py     # AI文案生成
│   ├── douyin_api.py    # 抖音 API
│   ├── oceanengine_service.py  # 巨量引擎 API
│   └── openclaw_service.py     # 客服 AI
├── templates/           # 模板
│   ├── schedule/        # 排班模块化 partial
│   └── *.html           # 页面模板
├── static/              # 静态资源
└── data/                # 运行时数据（DB/配置/视频）
```

## License

MIT
