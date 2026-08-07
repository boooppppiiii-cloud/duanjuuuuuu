# 剧枢（P3）

面向短剧海外社媒运营团队的共享工作台。应用按“账号总览 → 剧库 → 内容工厂 → 一键发布 → 管理”组织日常工作，既可在本机运行，也可部署到团队服务器。

P3 的原则是：业务数据只来自本地真实素材或平台官方接口。缺少凭证、权限不足、接口失败或模型未配置时，页面会显示阻塞原因，不生成模拟结果，也不会把本地文件包记为发布成功。

## 已实现的工作流

1. **首页 / 账号总览**：集中展示账号矩阵真实指标、发布内容状态和完整粉丝运营工作台，可同步评论、识别舆情并人工回复。
2. **剧库 / 共享素材池**：只管理近期准备运营的剧目，不代替公司现有全量剧目后台；本机运行时可登记已有文件夹，服务器运行时由浏览器分片上传到共享目录。
3. **内容工厂**：用本地 Whisper 把原始剧集拆成带时间轴的详细脚本，结合 ffmpeg 音量突变和情绪词识别高能点，识别色情/暴力文本风险，再完成批量剪辑、字幕、规格化、视觉敏感检测和人工终审。分析结果保存在剧目目录的 `factory_analysis.json`。
4. **一键发布**：先按账号运营策略使用 Gemini 或通义千问生成标题、文案和封面，再进入 YouTube、TikTok、Facebook、Instagram 官方发布接口或 Meta SFS 官方投递。
5. **管理**：集中配置平台开发者应用、OAuth/手动账号连接和账号运营策略。账号通过官方接口检测后才可发布。

## 首次启动

在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r backend\requirements.txt
cd frontend
npm install
cd ..
Copy-Item .env.example .env
.\start.ps1
```

打开 `http://127.0.0.1:5174`。接口文档位于 `http://127.0.0.1:8000/docs`。

`.env` 中的实际密钥由使用者配置，不应提交到版本库。应用内直接保存密钥时必须配置 `CREDENTIAL_SECRET`；若不希望密钥进入数据库，可在账号配置页只填写环境变量名。

## 平台连接顺序

1. 打开“管理”→“账号连接”→“开发者应用与 OAuth”。
2. 把页面显示的回调地址填入对应平台开发者后台。
3. 配置 Client/App ID 与 Secret，然后点击“连接账号”。
4. OAuth 完成后刷新页面，并执行一次“检测”。
5. 账号显示“已连接”后，才会出现在发布台和评论同步页面。

手动连接时可以填写平台 ID、Access Token、Refresh Token 与客户端凭证。页面不会回显已保存的密钥。

## 关键环境变量

参考 [.env.example](./.env.example)：

- `CREDENTIAL_SECRET`：应用内凭证加密密钥。
- `PUBLIC_API_ORIGIN` / `PUBLIC_UI_ORIGIN`：OAuth 回调使用的后端和前端地址。
- `PUBLIC_MEDIA_BASE_URL`：Instagram 从本地成品拉取视频时使用的公网 HTTPS 后端地址；未配置时发布页要求填写外部 HTTPS 视频地址。
- `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` / `GOOGLE_DRIVE_PARENT_FOLDER_ID`：Meta SFS 投递包上传配置。
- `GEMINI_API_KEY` / `QWEN_API_KEY`：智能文案、底图和深度分析。
- `FFMPEG_BINARY` / `FFPROBE_BINARY`：本地媒体处理工具。

## 本地素材目录

```text
media/dramas/<剧名>/episodes/   # 原始剧集
media/dramas/<剧名>/stills/     # 官方剧照
media/dramas/<剧名>/basemaps/   # 生成后待人工批准的底图
media/bgm/<题材>/               # BGM 与来源说明
media/assets/                   # 字体、角标、片尾
media/clips/                    # 干净版与预览
media/posts/                    # 封面与发布前最终视频
```

## 数据保存边界

| 数据 | Docker 服务器位置 | 保存规则 |
| --- | --- | --- |
| 账号连接、加密凭证、首页数据、评论、策略、剧目元数据、发布记录 | `backend/data/app.db` | 服务器共享，所有操作员读取同一份数据 |
| 原片、封面、剧照、内容工厂成品、高能点、Meta 投递包 | `media/` | 服务器共享，通过浏览器上传或由服务器生成 |
| 离线翻译语言包 | `backend/data/argos/` | 服务器持久化，首次安装后复用 |
| 运行日志 | `logs/` | 服务器持久化并自动轮转 |
| Meta 合规文件夹的操作员副本 | 操作员电脑 | HTTPS 下可直接选择本机目录；HTTP IP 访问时自动下载 ZIP |

数据库内的媒体路径会在工作区从 Windows 本机迁移到 Linux 服务器后自动重定位到当前 `media/`，避免只迁移数据库后留下失效的旧盘符路径。

## Docker 部署

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f backend
```

生产环境应通过 Nginx/Caddy 配置 HTTPS，不要直接公开后端端口。OAuth 回调和 Instagram 临时媒体地址都必须使用实际可访问的 HTTPS 域名。

## 验证

```powershell
$env:PYTHONPATH="backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q --basetemp=tmp\pytest
cd frontend
npm run build
```

媒体链路可运行 `scripts/smoke_test.py --fast`。该脚本使用隔离数据库和测试素材，不会写入正式业务库，也不会调用平台发布接口；最后一步验证未连接账号一定被发布保护拦截。
