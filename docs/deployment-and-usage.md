# 知行研学部署及使用指南

本指南适用于 Windows 上的 V2 本机部署。平台入口是 [127.0.0.1:5183](http://127.0.0.1:5183)，由 FastAPI 提供 API 和前端构建产物。Docker Desktop 运行 PostgreSQL 和 DeepTutor，分别使用本机端口 55433 和 18001。这个配置适合个人使用和受控演示；如需对外提供服务，先按[运行维护说明](operations.md)规划 HTTPS、访问控制、凭据和备份。

## 首次部署

准备 Git、PowerShell、Python 3.12、uv、Node.js 24（含 npm）和已启动的 Docker Desktop（Linux 容器）。初次安装需要能访问依赖包和容器镜像仓库。已有项目副本时，从项目根目录开始执行。

```powershell
git clone --branch refactor/deeptutor-native https://github.com/nihao169/kaoyan.git
Set-Location kaoyan
.\scripts\init.ps1
npm --prefix frontend run build
```

初始化脚本安装依赖，同时初始化一套旧版开发库；下方的 V2 发布库独立，**不会继承旧版演示账号或学习数据**。若本机脚本执行策略拦截，可用 `powershell -ExecutionPolicy Bypass -File scripts/init.ps1` 单次运行，不必改系统策略。

使用助教、出题和 AI 诊断前，在运行部署的 PowerShell 进程或 Windows 用户环境中设置自己的 `DEEPSEEK_API_KEY`。V2 安装脚本检测到它后会为 DeepTutor 配置模型。密钥只留在本机；不要写入命令历史、仓库或截图。如果使用自备模型，DeepTutor 需配置可共享的 API Key 模型；资料索引还需要可用的嵌入配置，详见 [DeepTutor 接入说明](deeptutor-native.md)。修改用户级环境变量后，重新打开终端再部署。

```powershell
.\scripts\setup-v2.ps1 -Release
.\scripts\start-release-v2.ps1 -MasteryReviews
.\scripts\status.ps1 -RuntimeName services-v2-release
```

`setup-v2.ps1` 创建或迁移 V2 发布库，准备并启动 DeepTutor。首次启动可能需要等待模型和索引服务就绪。`-MasteryReviews` 开启可关联到项目的独立复习队列；成功后脚本会记住这一设置。

| 检查地址 | 预期 |
| --- | --- |
| [平台首页](http://127.0.0.1:5183) | 能打开登录页 |
| [业务健康检查](http://127.0.0.1:5183/health/ready) | `status: ready`，显示数据库迁移版本 |
| [助教健康检查](http://127.0.0.1:5183/health/ai) | `status: ready`，表示 DeepTutor 可连通；还需做一次真实出题或助教检查，确认模型可用 |
| [平台接口文档](http://127.0.0.1:5183/docs) | 能找到 `/api/v2/learning-projects/{project_id}/attempt-history` |

## 注册并体验学习流程

在登录页点「没有账号？开始自主学习」。**账号**是登录用的用户名，**称呼**是平台显示的名字。首次启动的发布库没有预设的 `student`、`teacher` 或 `admin` 账号；个人学习可自行注册，体验教师作业则需已有权限的教师和同班学生账号。

示例资料在仓库的[三场景完整流程包](../测试导入资料/三场景完整流程包/00_导入与测试顺序.md)。这些文件不会自动进入项目。用三个独立项目体验下表流程：

| 场景 | 建项后准备 | 就绪后从「与助教学习」开始 |
| --- | --- | --- |
| 首次学习 | 在「课程与资料」上传 `01_新课学习_实践与认识.md` | 生成并确认学习大纲，按今日任务学习和做理解检查 |
| 期末复习 | 上传 `02_期末复习_辩证方法综合复习.md`，另点「确认考试范围」选择章节或填写范围 | 生成复习范围，从摸底进入薄弱点补学和综合复测 |
| 考研学习 | 课程选考研政治、目标年份选 2027；上传 `03_考研备考_政治专题讲义.md`，再导入 `04_2027模拟考纲.md` 或同名 JSON，任选一种 | 生成并确认考纲学习路线，开始专题；可导入 `05` 综合卷或 `06` 短卷测试原卷练习和计时。模拟卷不替代真题阶段要求的有权使用的往年真题 |

上传之后等资料就绪。上传文档提取考纲或试卷时，核对原文和提取结果，再确认入库。精读和资料查找在项目内进行，笔记和闪卡也保存在对应项目。

- **集中练习**：从「与助教学习 → 集中练习」设置单选、多选和分析题的数量，合计 1–10 题；可选择范围，也可按当前项目范围出题。新生成的集中练习不限时，保存草稿后可返回继续，整组交卷后查看反馈。限时模考请从试卷入口开始。
- **到期复习**：从所属项目的「与助教学习」查看待办；已进今日任务的复习从今日任务继续。提交后到「学习报告 → 作答记录」选择项目，再按「复习」筛选。未提交的题卡不会出现在报告。
- **错题诊断**：在「自主学习」查看个人项目中答错或被 AI 明确评为未达标的题，可手动发起诊断。「教师作业」是另一套记录；自主作答和诊断不会同步给教师。

## 更新、停止与排查

有现用数据时，先在原运行目录按 [V2 备份说明](v2-release.md#备份与恢复)执行 `scripts/backup-v2.ps1 -Release`，确认快照可验证，再更新分支。更新前停止本机发布服务；如已改动 DeepTutor 补丁，在重新初始化容器之前构建新标签。下面的版本标签应对应本次部署的代码版本。

```powershell
.\scripts\stop.ps1 -RuntimeName services-v2-release
# 更新工作区代码后，重新安装依赖并构建前端。
.\scripts\init.ps1
npm --prefix frontend run build
$env:ZX_DEEPTUTOR_IMAGE = "zhixing-deeptutor-native:release-$(git rev-parse --short HEAD)"
docker build --pull=false -t $env:ZX_DEEPTUTOR_IMAGE integrations/deeptutor
.\scripts\setup-v2.ps1 -Release
.\scripts\start-release-v2.ps1
```

若升级只改了平台代码，且 DeepTutor 已配置并运行，可跳过镜像构建，用 `setup-v2.ps1 -Release -SkipTutor` 保留原配置。仅修改挂载的 `integrations/deeptutor/bridge.py` 时，也要重启 DeepTutor 进程才能加载新接口：`docker restart zhixing-v2-deeptutor-1`。不要删除数据目录。停止平台服务的脚本只停本工作区登记的 API 和任务进程，Docker 中的数据库和助教服务继续运行。

| 现象 | 优先检查 |
| --- | --- |
| 「作答记录」和「错题诊断 → 自主学习」都显示「资源不存在」 | 查看 5183 的接口文档是否有 `attempt-history`。缺少该接口时，从当前代码重启发布服务，确认前后端使用同一版本。 |
| 报告显示「助教作答暂不可读取」 | 平台仍可能显示已保存的整卷记录。检查 `/health/ai` 和 `docker logs --tail 100 zhixing-v2-deeptutor-1`；若日志显示 `/internal/personal-attempts` 返回 404，确认容器挂载的是当前代码并重启 DeepTutor，再刷新报告。 |
| 资料上传成功但仍不能出题 | 在项目中确认范围和必备资料都已就绪，检查索引状态、DeepTutor 模型及嵌入配置。扫描 PDF 先做 OCR。 |
| 5183 已被占用或启动失败 | 运行 `scripts/status.ps1 -RuntimeName services-v2-release`，检查 `.runtime/services-v2-release.*.log` 和 PostgreSQL 容器状态。先确认端口归属，再用对应工作目录的停止脚本。 |

V2 发布库使用 PostgreSQL，原件和 DeepTutor 数据分别在 `data/v2-release` 和 `data/v2-deeptutor`；本机密钥和日志在 `.runtime`。备份时一起保护这些数据，恢复先写入新的目录和数据库。进一步的项目权限、AI 调用和历史规则见[项目学习流程](project-learning.md)。
