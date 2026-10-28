# 知行研学平台

面向长期维护的考研学习与教学管理平台。首个实施科目为考研政治，采用 React + FastAPI 模块化单体，提供学生学习、教师评价与内容治理三条闭环。

## 文档

- [总体架构设计](docs/architecture.md)：长期业务边界、数据模型、权限、版本和演进条件。
- [架构决策](docs/adr/0001-modular-monolith.md)：为什么采用模块化单体与分阶段基础设施。
- [运行维护](docs/operations.md)：配置、启动停止、备份恢复、数据库迁移和模型接入。
- [接口契约](docs/openapi.json)：生成的 OpenAPI；运行后可访问 http://127.0.0.1:8000/docs。
- [验收记录](docs/verification.md)：实际完成的测试、边界与限制。

## 本机启动

前置环境：Node.js 24、Python 3.12、PowerShell。推荐安装 uv 管理 Python 环境。依赖版本已锁定，不依赖系统全局 Python 包。

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-document-converter.ps1
powershell -ExecutionPolicy Bypass -File scripts/init.ps1 -DownloadModel
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

打开 [学习平台](http://127.0.0.1:5173)。启动脚本在后台运行 API、前端和 worker，不弹出终端窗口。

已安装依赖时，可使用 `scripts/init.ps1 -SkipInstall` 仅检查迁移并初始化演示数据。初始化幂等，不重置现有学习记录。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/status.ps1
powershell -ExecutionPolicy Bypass -File scripts/stop.ps1
```

停止脚本只停止记录在本项目清单中且身份匹配的进程，不通过端口批量结束程序。

## 演示账号

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 学生 | student | Zhixing2026! |
| 教师 | teacher | Zhixing2026! |
| 机构管理员 | admin | Zhixing2026! |

这些是本地演示账号，不应用于正式部署。教学内容均标明原创演示用途，初始状态为草稿，不自动冒充已审核内容。

### 首次体验顺序

1. 使用 teacher 登录，进入“教学内容”。
2. 逐份打开六份资料，核对原页、正文、知识卡、题目、答案、提示和评分要点，并确认原页与提取文本一致。
3. 点击“提交审核”，填写说明，再“审核确认并发布”。需要修改时可退回草稿。
4. 使用 student 登录，设置目标并完成基础诊断。
5. 练习时保存思考过程并提交。错误或辅助完成后，可确认错因、阅读知识卡并完成新题验证。
6. 正确且无提示的作答进入第 1、3、7 天复习安排；未到期不能提前完成。
7. 提交分析题后，用 teacher 查看作答详情并评分。学生可以提出异议，由教师复核生成评价修订。

演示内容包含六模块、18 张知识卡和60道题，另附七份原创 DOCX 与对应 PDF 原页样例。形势与政策使用虚构材料训练分析方法，不提供最新时政结论。新题耗尽时明确显示待补充，不伪装为新题。

## 可选 AI 服务

将 `.env.example` 复制为 `.env`，只在服务端设置：

```dotenv
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_API_KEY=填写你自己的密钥
```

网关应兼容 `POST /chat/completions`、JSON 结构化输出和标准消息响应。修改后重启 API 与 worker。

未配置模型时，评分、审核资料检索、静态递进提示、补学、复习和教师评分都可使用；AI 入口明确提示未配置。DeepSeek 支持当前题目答疑、四级提示、提交后的错因与分析题辅助评价，以及教师教案草稿。提示和答疑会标记辅助作答；诊断期间禁止调用。AI 建议不直接写入正式成绩。不要将真实密钥提交到代码仓库。

### 真实 AI 验收与交付

密钥只填写在本机 `.env` 的 `MODEL_API_KEY`，不发送到聊天、不提交 Git。重启 API 与 worker 后，可使用 admin 的“AI 服务状态”测试真实连接。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-real-ai.ps1
```

该命令建立独立验收数据库，通过真实页面调用 DeepSeek；不会覆盖演示库。结果写入 `.runtime/real-ai-acceptance.json`，仍需人工检查解释、依据和提示边界。未配置 Key 时明确中止。真实 AI 验收通过前不推送最终交付。

详细变更与限制见 [本轮补全验收](docs/completion-verification.md)。

## 测试

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test.ps1
```

测试使用独立临时数据库与独立 5181/8001 端口，不污染 data/platform.db。浏览器测试默认使用已安装的 Microsoft Edge；可设置 `PLAYWRIGHT_CHANNEL=chrome` 使用本机 Chrome。

分开执行：

```powershell
.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

更新接口后执行：

```powershell
.venv\Scripts\python.exe scripts/export_openapi.py
npm --prefix frontend run api:types
```

## 数据与维护

运行数据位于 data，日志和进程清单位于 .runtime；均不进入源码版本管理。schema 变更通过 Alembic 管理，不在应用启动时自动建表。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backup.ps1
```

备份脚本会停止本项目写服务，生成带摘要的数据库/原文/检查点快照，再恢复之前的运行状态。恢复默认写入新目录，具体操作见运行维护文档。

当前部署用于本机与受控演示。持续多人试用前需迁移 PostgreSQL、启用 HTTPS/Secure Cookie、替换演示凭据并配置机构的数据管理与备份策略。
