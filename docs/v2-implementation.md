# V2 核心实现与验收记录

日期：2026-11-05。本文记录实际实现；[V2 架构设计](architecture-v2.md)仍描述完整目标，两者不等同。

年度考纲与试卷、全文检索、原文定位及沿用旧网址的发布流程见 [V2 年度资料与切换](v2-release.md)。下文的「当前限制」是核心版首轮验收时的记录。

## 已实现

- 独立 PostgreSQL、Alembic 增量迁移、个人空间、学习项目、场景可用性、计划版本及每日时间预算。
- 学生入口调整为今日学习、学习项目、练习与模考、资料与笔记、学习报告；旧教师作业、错题与评分入口保留。
- 个人注册不要求教师班级。内部兼容现有登录契约，建立私有机构成员记录；自主学习的数据拥有者是个人空间。
- 个人文本、PDF、DOCX、TXT、Markdown 导入，以及关联有权限的教师启用资料。原件保存，解析在数据库事务及主事件循环之外执行。
- 阅读与草稿恢复、可选单选／多选／分析题、候选题独立模型校验、逐字引用及结构检查、无答案泄漏的题目读取。
- 客观题规则判分、提示辅助标记、答错补学、新题独立验证、1／3／7 天复习、暂缓任务、预算内今日安排与证据报告。
- 分析题 AI 训练反馈及百分制估分独立于旧正式成绩；没有教师确认的新训练分不会写入正式评价。
- 成组练习与模考、题目快照关联、两秒自动保存、修订冲突检测、答题卡、服务器截止时间、整组交卷；超时只使用服务器已保存答案。
- 模考期间服务端暂停本项目助教、提示与学习会话读取，交卷后恢复；错误结果进入补学。
- 个人笔记和可展开的记忆闪卡。闪卡自评暂未接入间隔复习。
- 独立 DeepTutor 1.7.1 实例，固定镜像摘要；签名身份交换映射为原生非管理员账号，用户／项目／资料范围分别隔离。
- 持久化 AI 运行、事件、租约、显式重试与取消状态。协议支持 native v2 WebSocket 和 Cookie 认证；模型失败不生成演示题。
- `/api/v2` 与旧 `/api/v1` 并存，OpenAPI 和前端生成类型已更新。
- 只读 SQLite 迁移工具、逐表和原件摘要核验、非空目标拒绝；一致性 PostgreSQL／文件／DeepTutor 备份及恢复到新库、新目录。

## 本机入口

本页记录的独立开发预览现使用 [http://127.0.0.1:5184](http://127.0.0.1:5184)，API 文档使用 [http://127.0.0.1:8003/docs](http://127.0.0.1:8003/docs)。正式本机入口及命令见 [V2 年度资料与切换](v2-release.md)。

V2 使用独立端口和 `.runtime/services-v2.json`，不会按端口批量停止其他项目。数据库位于 `data/v2-postgres`，资料位于 `data/v2`，DeepTutor 运行数据位于 `data/v2-deeptutor`。密钥在本机 `.runtime/v2-secrets.json` 和基础服务私有配置中，均不提交 Git。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-v2.ps1
powershell -ExecutionPolicy Bypass -File scripts/start-v2.ps1
powershell -ExecutionPolicy Bypass -File scripts/status.ps1 -RuntimeName services-v2
powershell -ExecutionPolicy Bypass -File scripts/stop.ps1 -RuntimeName services-v2
```

首次初始化应先按 README 准备 Python 与前端依赖，并启动 Docker Desktop。已有本机 DeepSeek 环境凭据会用于配置独立实例，不输出凭据。当前种子只建立演示账号和政治配置，不导入教学内容。可使用学生账号，或在登录页创建个人学习空间。

## 实际验证

| 验证 | 结果与证据 |
|---|---|
| 全量后端回归 | 78 项通过，全部使用临时 SQLite 数据库；包括现有教师工作流、Word 转换、V2 闭环、模考、伪造引用拦截及训练评价边界 |
| PostgreSQL | 11 项 V2 测试在专用 `zhixing_v2_test` 全部通过；测试配置拒绝其他数据库名称 |
| 浏览器学习循环 | 受控服务验证项目创建、资料学习、草稿恢复、出题、答错补学、新题答对、复习安排及报告；检查手机宽度无横向溢出 |
| 浏览器模考 | 验证自动保存、刷新恢复、服务端助教限制和交卷反馈；发现并修复 React 19 下静态确认框不显示的问题 |
| 浏览器注册 | 验证个人注册后可进入学习空间且没有教师班级；三条 V2 浏览器回归全部通过 |
| 前端 | TypeScript、生产构建和 6 项 API 客户端测试通过；仍存在构建产物体积提示 |
| 真实 DeepTutor | 真实身份交换与流式问答通过；另在临时业务库完成两道政治题的生成、独立模型校验、错误补学及复习安排 |
| 迁移演练 | 离线测试 SQLite 快照及原件成功导入新的 PostgreSQL 演练库，逐表及文件摘要校验通过；未迁移或覆盖旧正式库 |
| 备份恢复 | 协调停止本项目写服务后备份，恢复到独立 `zhixing_v2_restore_acceptance_20261105` 及新目录，核对账号数和迁移版本 |

真实服务报告在 `.runtime/v2-real-acceptance.json`，保留题干、参考答案、原文与解析供复核。受控浏览器结果不能替代真实调用；真实调用通过也不代表教师已完成教学内容审核或证明提分效果。

```powershell
.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run test:api
npm --prefix frontend run test:e2e:v2
powershell -ExecutionPolicy Bypass -File scripts/test-v2-postgres.ps1
```

`scripts/verify-v2-real.py` 明确执行真实模型调用并产生费用，使用临时业务数据库；不在常规自动回归中执行。旧教师浏览器脚本继续保留，需准备旧本地检索模型，本轮主要通过既有后端回归验证其兼容性。

## 当前限制与后续阶段

- 本轮交付核心闭环，不代表完整 V2 架构全部完成。独立章节学习、期末备考和其他学科按已确定范围后置。
- 当前助教采用有界资料片段上下文，每份最多前12000字、总计最多24000字；不是 DeepTutor 原生全文 RAG 或完整知识库同步。页面和生成结果展示覆盖限制。
- 普通助教自由文本引用仍标为未验证；只有经过原文匹配的生成题和评价能进入对应学习证据流程。
- 原文定位目前以提取文本和逐字引用为主，尚未完成 PDF 原页高亮、块编辑器、交互可视化及知识图谱。
- 完整年度考纲、正式真题库、阶段性内容覆盖规划和跨课程知识点映射尚未建设；当前报告不输出全科预测分。
- V2 AI 队列已有持久化及租约，仍与旧任务共用 Worker；独立并发配额、实时原生运行重连、完整用量统计和物理清理队列需继续完善。
- 取消执行依赖下游事件确认；执行中断不自动盲目重发模型请求。模考到时由打开的页面触发交卷，离线后重新打开按服务器已存答案交卷，尚无服务端主动到时交卷任务。
- 用户主动录入的个人资料按私有范围可直接学习；生成内容仍需检查质量，公共内容和正式成绩继续走教学治理。
- 本机为开发预览部署，尚未交付生产反向代理和公网部署配置。已有历史库保持原状；正式切换需要使用离线快照及迁移工具另行实施。

## 迁移与备份操作

迁移先使用一致性离线 SQLite 快照。目标 PostgreSQL 必须已迁移到最新结构且没有业务记录；准备迁移目标时使用 `setup-v2.ps1 -SkipSeed`，不得向已有 V2 库重复导入。`DATABASE_URL` 通过环境提供，不将口令写入命令参数或报告。

```powershell
.venv\Scripts\python.exe scripts/migrate-v2.py --source <离线快照.db> --source-data <快照资料目录> --report .runtime/migration-inventory.json
.venv\Scripts\python.exe scripts/migrate-v2.py --source <离线快照.db> --source-data <快照资料目录> --target-data <全新资料目录> --report .runtime/migration-applied.json --apply
powershell -ExecutionPolicy Bypass -File scripts/backup-v2.ps1
.venv\Scripts\python.exe scripts/snapshot-v2.py validate <备份目录>
.venv\Scripts\python.exe scripts/snapshot-v2.py restore <备份目录> --destination <全新恢复目录> --database-name zhixing_v2_restore_<名称>
```

V2 协调备份包含基础服务私有配置和凭据，只能保存在受保护的本机目录，不作为公开产物或 Git 附件。恢复始终使用新库和新目录，不自动改变活动环境。旧 LangGraph 检查点保留在旧备份中，不作为新版运行恢复入口。
