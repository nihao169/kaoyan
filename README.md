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
2. “导入新资料 → 上传文件”，上传文字型 PDF、DOCX、TXT 或 Markdown（最多50MB、1000页；扫描页不支持OCR）。可使用独立文件 `测试导入资料/政治模拟讲义_实践认识与辩证方法.md`，该文件不会自动导入平台。
3. 解析和索引就绪后，调整题型数量、可选章节及已启用补充资料，点击一次“启用并生成”。默认12题：6单选、4多选、2分析题，单批最多30题。无需审核说明或二次确认。
4. 等待 Agent 提取知识卡、出题、独立校验。失败可查看原因、重试；未通过校验的内容不进可用题库。生成范围有限，不等于覆盖整本教材。
5. “作业与批阅”中选题，选择班级、填写作业名称，一次发布。题目、答案、评分和来源版本固定。
6. student 首页打开教师作业，逐题作答、保存思考过程，整组提交。目标设置可选，没有基础诊断前置。客观题系统判分；分析题 AI 初评待教师确认，不计入正式成绩。
7. teacher 从“作业与批阅 → 查看作答 / 批阅”确认或修改分析题评分；学生可提出异议并保留评价历史。
8. student 在“错题诊断”查看原选项、错选漏选、思考过程和原文，手动点“AI诊断”，完成后手动点“生成针对性练习”。个人新题不进入班级题库。独立答对后进入第1、3、7天复习。

正常初始化只准备账号、班级及政治教学和评分配置，不自动导入演示资料、知识卡或题库。2026-10-29已按要求清空旧内容与学习数据，删除旧模拟资料文件，保留账号和模型配置；旧内容只存在于清理前备份中。自动化回归所需演示数据仅在隔离测试数据库中显式启用。

## AI 服务

将 `.env.example` 复制为 `.env`，只在服务端设置：

```dotenv
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_API_KEY=填写你自己的密钥
```

网关应兼容 `POST /chat/completions`、JSON 结构化输出和标准消息响应。修改后重启 API 与 worker。

也支持环境变量 `DEEPSEEK_API_KEY`，空的配置值不会覆盖已配置密钥。修改后重启 API 与 worker。新资料出题、错题诊断与针对性练习需要真实模型；未配置或失败时明确提示，不回退演示题。客观题系统判分和教师评分仍由确定性接口完成。所有新 Agent 引用限于已启用的教师资料，AI 初评不直接形成正式成绩。

### 真实 AI 验收与交付

密钥只填写在本机 `.env` 的 `MODEL_API_KEY`，不发送到聊天、不提交 Git。重启 API 与 worker 后，可使用 admin 的“AI 服务状态”测试真实连接。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-real-ai.ps1
```

该命令建立独立验收数据库，通过真实页面调用 DeepSeek；不会覆盖当前学习库。结果写入 `.runtime/real-teaching-acceptance.json`，仍需人工检查题目、答案、解释、依据和提示边界。未配置 Key 时明确中止。真实 AI 验收通过前不推送最终交付。

当前流程测试见 [人工验证链路](docs/manual-test-guide-2026-10-29.md)。旧浏览器脚本 `platform.spec.ts`、`extensions.spec.ts` 和旧验收文档只记录此前流程，不代表本次新流程通过。

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
