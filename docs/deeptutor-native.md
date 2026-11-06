# DeepTutor 原生能力接入与切换

知行的前端只访问 `/api/v1` 和 `/api/v2`。知行保存原始资料、版本、访问权限、计划、作答和正式成绩；DeepTutor 只执行检索及模型任务。分析题的教师初评仍是草稿。项目内已核对的引导建议须由学生主动加入计划，阅读和提示不会增加独立掌握证据。

基础镜像固定为 DeepTutor v1.7.1，摘要见 [`Dockerfile`](../integrations/deeptutor/Dockerfile)。知行只维护原生出题的题型与字段补丁。用以下命令构建预览镜像，部署时将 `ZX_DEEPTUTOR_IMAGE` 指向发布后的不可变摘要：

```powershell
docker build --pull=false -t zhixing-deeptutor-native:1.7.1 integrations/deeptutor
```

预览使用独立数据库、DeepTutor 数据目录、桥接密钥和回环端口。不要复用 5183 的业务库、`data/v2-release` 或 DeepTutor 数据卷。把 `integrations/deeptutor` 只读挂载到 `/integration`，以 `python -m uvicorn bridge:app --app-dir /integration --host 0.0.0.0 --port 8001` 启动，绑定到 `127.0.0.1:18012`。在预览数据目录的 `user/settings/auth.json` 中设置 `"enabled": true` 后再启动。通过 DeepTutor 配置命令配置模型及 384 维中文嵌入。开发机可以用 `scripts/serve_local_embeddings.py` 提供已有的多语 MiniLM 模型作为 OpenAI 兼容嵌入服务。密钥只放环境或忽略的运行目录。

把隔离服务的桥接密钥保存到 `.runtime/tutor-native-preview-<id>/bridge.key`，然后运行：

```powershell
.venv/Scripts/python.exe scripts/verify-native-knowledge.py .runtime/tutor-native-preview-<id>
.venv/Scripts/python.exe scripts/verify-native-knowledge.py .runtime/tutor-native-preview-<id> --lessons
.venv/Scripts/python.exe scripts/verify-native-knowledge.py .runtime/tutor-native-preview-<id> --student
.venv/Scripts/python.exe scripts/verify-native-questions.py .runtime/tutor-native-preview-<id>
powershell -ExecutionPolicy Bypass -File scripts/test-v2-postgres.ps1 -Database zhixing_v2_test_native
```

探针默认使用全新的 SQLite 库，也可将 `ZX_NATIVE_ACCEPTANCE_DATABASE_URL` 设为本机独立的 `zhixing_tutor_native_*` PostgreSQL 库。教师浏览器验收使用 `ZX_E2E_ISOLATED_DATABASE_URL` 指向另一个同样命名的空库，启用教师两项开关和知识库，设置 `ZX_REAL_AI=1`、`ZX_NATIVE_TEACHING_E2E=1`，执行 `npm --prefix frontend run test:e2e`。两端真实流程通过并验证 5183 的备份后，按下表顺序启用。开发环境默认关闭，正式启动脚本默认开启五项能力。需要回退时，在启动脚本的调用进程中将对应环境变量显式设为 `false`。

| 环境变量 | 生效范围 |
|---|---|
| `DEEPTUTOR_NATIVE_KNOWLEDGE` | 项目资料索引与答疑；已索引资料仍可在关闭后异步清理 |
| `DEEPTUTOR_NATIVE_QUESTIONS` | 新建个人项目练习和错后新题；要求知识库已启用 |
| `DEEPTUTOR_NATIVE_LESSONS` | 原生精读、讲题、学习引导；要求知识库已启用 |
| `DEEPTUTOR_NATIVE_TEACHER_QUESTIONS` | 教师批量出题及作业错题变式 |
| `DEEPTUTOR_STRUCTURED_TEACHER` | 教师建议类任务使用 DeepTutor 结构化聊天 |

索引按授权资料版本创建；失败可在项目资料页重试。撤回资料后，旧结果读取立即受限，下游副本由任务清理。已有运行绑定创建时的执行后端，状态不明时提示人工处理。回退时关闭相关开关，让新任务切回已验收的路径；保留原作答、成绩和运行记录。发布前核对索引状态、模型失败、耗时、引文核对和服务可提供的用量；无记录的用量不可当作零成本。

原生知识库启用后，学生分析题训练评价也使用原生检索和结构化 Chat。个人 TXT/Markdown 优先上传原件；PDF 使用分页面文本，以保留可核对的原页位置，DOCX 使用知行已提取的文本。知行的全文查阅入口仍可独立使用。精读在原生阅读工作区内复用同一会话；已确认的 Mastery Path 可以从项目恢复，资料范围变更后需重新生成。阅读、原生进度和自评仍不写入正式成绩或独立掌握证据。

教师三项相关开关全部开启时，新导入资料只做原文提取，启用或生成时由 DeepTutor 按授权章节建索引，不再同时为新资料建立旧版向量。已有旧索引和在途任务保留。回退教师开关后，原生阶段新增的资料可从原有索引界面重建旧索引；回退前应先演练一份新资料。原生题库、复习调度、笔记和闪卡的写入切换留待核心链路验收后分批完成。

教师真实浏览器验收可直接运行 `powershell -ExecutionPolicy Bypass -File scripts/test-real-ai.ps1 -NativePreview .runtime/tutor-native-preview-<id>`，脚本创建独立 PostgreSQL 库并启用教师原生开关。学生真实探针使用同一预览服务，分别检查 `--lessons` 与 `--student`；这两个选项可以组合运行。

教师工作流为每个原生步骤保存运行 ID。超时后可从原运行恢复。如果下游未确认接收，先核对下游状态，避免再次出题。DeepTutor 明确标记某个 Chat 步骤因传输错误结束时，仅重试该步骤一次，保留前面的原生出题结果。

2026 年 11 月 6 日，学生和教师真实流程均通过，教师验收使用独立 Docker 数据卷和 PostgreSQL。抽查了教师批量生成的单选、多选、分析题以及三道错题变式。正式库、原件和 DeepTutor 数据完成协调备份，已恢复到隔离目录及数据库并演练候选迁移。5183 按阶段启用五项能力，正式 DeepTutor 的签名知识库及真实 Chat 探针通过。

固定版后续兼容性：Practice 的题目读取包含完整题库条目，接入前须在知行接口过滤答案并验证题目归属；不能直接将上游响应发给未提交的学生。Mastery Path 的自定义复习间隔通常从实际复习时间计算，知行的第 1、3、7 天从独立通过的同一锚点计算。迟到复习语义未验证等价前，保留知行调度，不同时启动两套队列。

发布检查：先确认 5183 由哪个工作目录、哪份运行清单启动。`scripts/backup-v2.ps1 -Release` 只能停止它所在工作目录登记的服务；如果 5183 临时从基线工作目录启动，先在那个目录按对应清单停服务，确认写入进程已退出，再执行备份。分别核对并在隔离环境验证业务库 `zhixing_v2_release`、资料原件和 DeepTutor 数据卷的备份，再运行发布迁移。按知识库、学生出题与教学、教师出题与结构化评价的顺序启用；旧路径只在学生和教师的真实流程都通过、旧任务清空且回退演练通过后退役。

## 第二轮项目试点

- `DEEPTUTOR_PRACTICE_PROJECTS` 和 `DEEPTUTOR_RECORDS_PROJECTS` 都接收以空格分隔的项目 ID，默认空。个人题库按知行题目 ID 把经过原文核验的 AI 题同步到独立的 DeepTutor 项目账户。个人任务提交后，客观题使用 Practice 的判分接口；知行验证结果与考研计分规则一致后记录作答、掌握证据和复习安排。测评快照和分析题评价走各自现有流程。
- `DEEPTUTOR_TEACHER_BANK_ORGS` 接收以空格分隔的机构 ID，默认空。教师题库使用独立的机构级原生目录，知行仍按教师角色、资料可见范围和题目状态过滤后才查询和返回。新旧题目版本仍由知行区分，已布置作业继续读取发布时的版本。
- 设置学习记录名单后，由项目所有者调用 `POST /api/v2/learning-projects/{project_id}/notes/migrate`。每次最多向下游写入 25 条，全部比对通过才把项目标为已迁移。下游超时后可重跑。移出名单会暂停已迁项目的写入，读取仍走原生。等当前写入请求结束，再由所有者调用同路径下的 `/notes/restore`，完整核对并导回新增记录后恢复本地写入。
- 项目答疑历史使用原运行的会话和轮次标识，返回知行核对过的正文与引用。以前未保存原生会话标识的记录直接读取历史结果。资料范围变化或有活跃模考时沿用知行的访问限制。
- 隔离预览以最新桥接代码启动，运行 `scripts/verify-native-knowledge.py <preview> --phase2 --student --lessons`。该探针核对真实原生题库、客观题判分、笔记迁移、闪卡、会话读取和导回。教师目录试点需另过机构级隔离验收。原生复习调度需通过固定锚点语义验证后再开放。
