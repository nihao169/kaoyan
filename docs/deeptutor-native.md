# DeepTutor 原生能力接入与切换

知行的前端只访问 `/api/v1` 和 `/api/v2`。知行保存原始资料、版本、访问权限、计划、作答和正式成绩；DeepTutor 只执行检索及模型任务。分析题的教师初评仍是草稿。项目内已核对的引导建议须由学生主动加入计划，阅读和提示不会增加独立掌握证据。

基础镜像固定为 DeepTutor v1.7.1，摘要见 [`Dockerfile`](../integrations/deeptutor/Dockerfile)。知行只维护原生出题的题型与字段补丁。用以下命令构建预览镜像，部署时将 `ZX_DEEPTUTOR_IMAGE` 指向发布后的不可变摘要：

```powershell
docker build --pull=false -t zhixing-deeptutor-native:1.7.1 integrations/deeptutor
```

预览使用独立数据库、DeepTutor 数据目录、桥接密钥和回环端口。不要复用 5183 的业务库、`data/v2-release` 或 DeepTutor 数据卷。把 `integrations/deeptutor` 只读挂载到 `/integration`，以 `python -m uvicorn bridge:app --app-dir /integration --host 0.0.0.0 --port 8001` 启动，绑定到 `127.0.0.1:18012`。启用 DeepTutor 账号验证，通过其配置命令配置模型及 384 维中文嵌入；开发机可以用 `scripts/serve_local_embeddings.py` 暴露已有的多语 MiniLM 模型作为 OpenAI 兼容嵌入服务。密钥只放环境或忽略的运行目录。

把隔离服务的桥接密钥保存到 `.runtime/tutor-native-preview-<id>/bridge.key`，然后运行：

```powershell
.venv/Scripts/python.exe scripts/verify-native-knowledge.py .runtime/tutor-native-preview-<id>
.venv/Scripts/python.exe scripts/verify-native-knowledge.py .runtime/tutor-native-preview-<id> --lessons
.venv/Scripts/python.exe scripts/verify-native-knowledge.py .runtime/tutor-native-preview-<id> --student
.venv/Scripts/python.exe scripts/verify-native-questions.py .runtime/tutor-native-preview-<id>
powershell -ExecutionPolicy Bypass -File scripts/test-v2-postgres.ps1
```

探针默认使用全新的 SQLite 库；也可将 `ZX_NATIVE_ACCEPTANCE_DATABASE_URL` 设为本机独立的 `zhixing_tutor_native_*` PostgreSQL 库。教师浏览器验收使用 `ZX_E2E_ISOLATED_DATABASE_URL` 指向另一个同样命名的空库，启用教师两项开关和知识库，设置 `ZX_REAL_AI=1`、`ZX_NATIVE_TEACHING_E2E=1`，执行 `npm --prefix frontend run test:e2e`。只有两端完整流程通过，才可备份 5183 的数据库和原件，再按下表顺序启用。默认所有开关关闭。

| 环境变量 | 生效范围 |
|---|---|
| `DEEPTUTOR_NATIVE_KNOWLEDGE` | 项目资料索引与答疑；已索引资料仍可在关闭后异步清理 |
| `DEEPTUTOR_NATIVE_QUESTIONS` | 新建个人项目练习和错后新题；要求知识库已启用 |
| `DEEPTUTOR_NATIVE_LESSONS` | 原生精读、讲题、学习引导；要求知识库已启用 |
| `DEEPTUTOR_NATIVE_TEACHER_QUESTIONS` | 教师批量出题及作业错题变式 |
| `DEEPTUTOR_STRUCTURED_TEACHER` | 教师建议类任务使用 DeepTutor 结构化聊天 |

索引按授权资料版本创建；失败可在项目资料页重试。撤回资料后，旧结果读取立即受限，下游副本由任务清理。已有运行绑定创建时的执行后端，状态不明时提示人工处理。回退时关闭相关开关，让新任务切回已验收的路径；保留原作答、成绩和运行记录。发布前核对索引状态、模型失败、耗时、引文核对和服务可提供的用量；无记录的用量不可当作零成本。
