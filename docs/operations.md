# 运行维护说明

> 本文保留旧环境操作。V2 的独立 PostgreSQL、DeepTutor、5183/8003 端口、启动停止及备份恢复见 [V2 实现与验收](v2-implementation.md)。不要将旧 SQLite 备份命令当作 V2 备份方式。

## 1 目录与环境

项目根目录为 D:\kaoyan；脚本从自身位置解析路径，不要求从特定终端目录运行。后端使用 .venv，前端依赖保存在 frontend/node_modules。

| 路径 | 内容 |
| --- | --- |
| data/platform.db | 业务数据库 |
| data/files | 原始资料，不作为公开静态目录 |
| data/workflows.db | LangGraph 检查点，首次 AI 执行时创建 |
| .runtime/services.json | 本项目启动的进程标识 |
| .runtime/*.log | API、前端与 worker 输出 |
| .runtime/backups | 默认备份位置 |
| .runtime/e2e-* | 浏览器测试隔离数据，不是真实学情 |

运行配置来自项目根目录 .env 或环境变量，环境变量优先。默认无需 .env 即可使用本机基础业务。

## 2 配置

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| DATABASE_URL | 项目 data/platform.db 的 SQLite URL | 首版业务存储 |
| DATA_DIR | 项目 data | 原件与检查点目录 |
| ALLOWED_ORIGIN | http://127.0.0.1:5173 | 允许写请求的前端来源 |
| SECURE_COOKIES | false | 本机 HTTP；HTTPS 部署设为 true |
| SESSION_HOURS | 8 | 服务端会话有效期 |
| MODEL_BASE_URL | https://api.deepseek.com | DeepSeek API 基地址，不含 /chat/completions |
| MODEL_NAME | deepseek-flash | 可配置的实际模型名称 |
| MODEL_API_KEY | 空 | 服务端密钥 |
| MODEL_TIMEOUT | 30 | 单次调用秒数 |

首版依赖锁定目标为 Python 3.12，Node.js 推荐 24。改变运行时后需重新解析并验证依赖，不能直接将系统环境当作交付环境。

## 3 启动与停止

执行 scripts/init.ps1 安装锁定依赖、迁移并初始化演示数据。执行 scripts/start.ps1 启动隐藏的三个进程，并检查 API 和前端就绪状态。使用 scripts/status.ps1 检查 PID 和健康信息。

脚本仅绑定 127.0.0.1。访问地址统一用 http://127.0.0.1:5173，避免 localhost 与 Cookie/Origin 配置不一致。端口被占用时脚本中止，不停止其他应用。

scripts/stop.ps1 核对工作区、命令行及进程创建时间后停止本项目进程。不要直接删除 services.json 来绕过身份检查。

手动调试时，API 使用 `python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`；worker 从根目录运行 `.venv/Scripts/python.exe scripts/run_worker.py`；前端在 frontend 运行 `npm run dev`。

## 4 健康与故障

- /health/live：进程可响应。
- /health/ready：迁移、业务表和数据目录可用。
- ai=not_configured：模型未配置，基础平台仍就绪。
- NOT_FOUND：记录不存在或不在当前访问范围。
- STALE_REVISION：页面版本落后，重新读取后再保存，不能覆盖他人修改。
- DIAGNOSTIC_RESTRICTION：诊断期间禁止资料和提示。
- CONTENT_REQUIRED：缺少审核内容或题目，不用自动生成内容填补。
- MODEL_*：模型超时、网络、格式或配置问题，原始作答保留。

日志通过 request_id 关联，不包含密钥或完整答案。查看 .runtime/api.err.log、worker.err.log 和 frontend.err.log。worker 会恢复租约过期任务，最多两次执行；不要把任务表失败标记当成评分失败，正式成绩由业务记录决定。

## 5 备份与恢复

使用 scripts/backup.ps1 做协调备份。脚本停止自己管理的 API/worker/前端，等待终止后使用 SQLite backup API 生成业务和检查点快照，并复制已引用原件；随后恢复原运行状态。独立手动启动的写进程需先自行停止。

快照包含 manifest.json，其中记录迁移版本、创建时间和逐文件 SHA-256，不包含 .env 或模型密钥。备份内含用户与学习数据，应按机构权限保管，不作为公开源码附件。

校验：

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe -m app.backup verify .runtime/backups/<backup-id>
```

恢复到一个尚不存在的新目录：

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe -m app.backup restore .runtime/backups/<backup-id> .runtime/restored-<new-id>
```

恢复检查摘要、SQLite integrity_check、foreign_key_check、迁移版本和来源原件引用。不会覆盖当前 data。验证后停止服务，把 DATABASE_URL 和 DATA_DIR 同时切到恢复目录再启动；确认学习记录与来源后保留旧目录作为回退。快照不能替代异地备份，持续试用时配置自动与异地备份。

## 6 数据库升级

新表结构使用 Alembic：生成迁移、审查具体 SQL、在独立数据库测试 upgrade/downgrade，再升级实际数据。升级前先备份。

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.venv\Scripts\python.exe -m alembic -c backend/alembic.ini check
```

迁移 PostgreSQL 前安装匹配驱动并建立独立验证环境，检查 UUID 字符串、JSON、ISO 时间、排序、约束、事务及恢复。不直接把 SQLite 专用备份脚本用于 PostgreSQL。

## 7 接口与持续集成

导出脚本生成 docs/openapi.json，openapi-typescript 生成 frontend/src/generated/api.d.ts；重要请求与学习响应使用生成类型。修改后执行后端测试、类型检查、构建与浏览器闭环。

.github/workflows/ci.yml 提供 Windows 下的自动检查配置。当前交付为本地工程，没有自动推送仓库或部署到公网；远端 CI 需在项目接入 Git 仓库后实际运行。

## 8 正式试用前的工作

持续多人使用前迁移 PostgreSQL；启用 HTTPS 和 Secure Cookie；替换演示账号；补齐机构账号停用、数据导出/保留/删除流程；配置自动备份、告警与集中指标；由教师确认正式内容及评测集。首版当前不承诺这些尚未部署的运营能力。


## 9 本轮资料与 AI 工作流

新增 `source_documents`、`chunk_embeddings`、`card_rules`、`ai_requests`、`teaching_referrals`、`lesson_drafts`，使用增量迁移保留原账号和学习记录。SQLite 事务使用 BEGIN IMMEDIATE 避免后台任务与页面操作同时升级写锁造成 BUSY_SNAPSHOT；多人高并发仍需迁移 PostgreSQL。

首次运行执行 `scripts/setup-document-converter.ps1`，仅将 LibreOffice 解压到 `.runtime/libreoffice`。DOCX 保留原件并转换固定版式 PDF，解析与索引成功后一次“启用并生成”。扫描页、加密或无文本文件会明确失败；不提供 OCR。修订原件须在新版本草稿中上传。支持PDF、DOCX、UTF-8 TXT/Markdown，最多50MB、1000页。

执行 `.venv/Scripts/python.exe scripts/setup_models.py --download --reindex` 下载实际向量模型；不稳定网络可改用 `scripts/download_embedding.py`，该脚本分段续传并核对官方 SHA256。运行时仅从本地加载，不静默联网下载。模型权重、下载分段与缓存均在 `data/models`，不提交仓库。`EMBEDDING_CACHE_DIR` 可指定独立缓存目录；清单保存模型提交版本，索引按模型提交区分。更换模型后使用“重建索引”或 `--reindex`。

现有 `/retrieval` 保留关键词模式兼容；添加 `mode=hybrid` 明确使用关键词与语义融合。DeepSeek 工作流实际调用混合检索。缺少权重或索引返回明确错误，不冒充成功。检索结果不使用共享缓存。

旧辅助任务仍通过 `/ai/requests` 保留。当前资料生成、错题诊断、针对性练习和分析题初评使用 `/agent-runs` 与 `teaching_agent` 后台任务，阶段续租180秒。失败可显式重试，不能改数据库状态来跳过校验。详见 [新流程架构](teacher-agent-architecture.md)。

密钥可用`MODEL_API_KEY`或进程环境中的`DEEPSEEK_API_KEY`，空值忽略。Windows用户变量改变后，启动服务的进程也需获得新环境。不要打印、提交密钥。`scripts/test-real-ai.ps1`使用独立数据库；受控适配器只在测试启动器中启用。

费用字段为按配置价格计算的估算美元值，包含价格版本，不代表供应商实际账单。模型输出仍须教师核对；引用审核不是事实正确性的保证。

备份新增原文件及固定版式 PDF；向量记录包含在数据库快照中，模型权重可重新下载。恢复后先核对模型版本，再重建索引。`.env` 不在备份或源码包中。
