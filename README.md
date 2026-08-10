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
- `DEVELOPER_EMAIL` / `DEVELOPER_INITIAL_PASSWORD`：预留开发者账号与首次启动密码。密码只放在服务器 `.env`，启动后写入 scrypt 哈希。
- `AUTH_SESSION_DAYS`：登录会话有效期。
- `SMTP_*`：可选邮箱验证邮件服务；不配置时是邮箱格式校验 + 密码注册，不代表已验证邮箱所有权。
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
| 用户、登录会话、用量账本 | `backend/data/app.db` | 服务器保存；密码只保存 scrypt 哈希，会话 Cookie 为 HttpOnly |
| 账号连接、加密凭证、首页数据、评论、剧目元数据 | `backend/data/app.db` | 服务器共享，所有已登录操作员读取同一份业务数据 |
| 内容识别结果、高能库 | 剧目目录 + `app.db` | 云端共享；已完成且分析版本一致时直接命中缓存，不重复调用模型 |
| 运营策略、账号与策略绑定、待上报本地事件 | 浏览器 `localStorage` | 按剧枢用户 ID 隔离，只留在当前浏览器；事件通过持久化 outbox 联网后上报 |
| 加工任务、个人成品、发布草稿/任务、Meta 投递包 | `app.db` + `media/` | 按登录账号隔离；现有 Web 版媒体加工仍需服务器临时执行和保存 |
| 云剧库成品 | `media/cloud-library/` | 仅用户主动上传后共享；同盘优先硬链接，不重复占用源成品磁盘块，跨盘才复制 |
| 原片、封面、剧照 | `media/dramas/` | 剧库共享，所有已登录操作员可查看 |
| 离线翻译语言包 | `backend/data/argos/` | 服务器持久化，首次安装后复用 |
| 运行日志 | `logs/` | 服务器持久化并自动轮转 |
| Meta 合规文件夹的操作员副本 | 操作员电脑 | HTTPS 下可直接选择本机目录；HTTP IP 访问时自动下载 ZIP |

数据库内的媒体路径会在工作区从 Windows 本机迁移到 Linux 服务器后自动重定位到当前 `media/`，避免只迁移数据库后留下失效的旧盘符路径。

开发者数据页只汇总服务器实际收到的事件。模型 token 仅采用供应商响应返回的真实用量，供应商未返回时记录为 `0`，不会估算。本地策略使用事件先进入浏览器 outbox，联网成功上报后才进入统计；如果用户在上报前清空浏览器数据，该部分无法由服务器恢复。

## Docker 部署

本机或局域网运行：

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f backend
```

生产环境使用内置 Caddy 自动管理 HTTPS。首先确保域名 A 记录指向服务器，服务器安全组/防火墙已放行 TCP 80、TCP 443 和 UDP 443，然后在 `.env` 中配置：

```dotenv
APP_DOMAIN=app.duanju.chat
FRONTEND_BIND_PORT=5174
CORS_ORIGINS=https://app.duanju.chat
PUBLIC_API_ORIGIN=https://app.duanju.chat
PUBLIC_UI_ORIGIN=https://app.duanju.chat
PUBLIC_MEDIA_BASE_URL=https://app.duanju.chat
```

启动生产环境：

```bash
docker compose --profile production up -d --build
docker compose --profile production logs -f caddy
```

新注册域名尚未完成公共 DNS 传播时，可先保持现有 HTTP 服务，用一次性等待脚本在解析生效后安全切换：

```bash
nohup ./deploy/enable_https_when_dns_ready.sh > ~/duanju-https-enable.log 2>&1 &
```

脚本默认等待最多 48 小时；Cloudflare DNS 和 Google DNS 均解析到服务器后，会自动启动 Caddy、申请证书并完成 HTTPS 健康检查。

Caddy 会自动申请、保存和续期免费证书，并将 HTTP 跳转到 HTTPS。`caddy_data` 与 `caddy_config` 卷必须保留，不要在日常重启时删除。OAuth 回调应配置为 `https://app.duanju.chat/api/integrations/oauth/youtube/callback`。

## 验证

```powershell
$env:PYTHONPATH="backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q --basetemp=tmp\pytest
cd frontend
npm run build
```

媒体链路可运行 `scripts/smoke_test.py --fast`。该脚本使用隔离数据库和测试素材，不会写入正式业务库，也不会调用平台发布接口；最后一步验证未连接账号一定被发布保护拦截。
