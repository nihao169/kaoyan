# V2 年度资料、引用与本机切换

按已确认的切换范围，新环境使用独立 PostgreSQL 库 `zhixing_v2_release` 和资料目录 `data/v2-release`。旧库和旧预览数据不导入；初始化只创建考研政治科目，不建立共享演示账号。正式入口使用 `http://127.0.0.1:5183`，只对本机开放；5173 保留给占用它的现有服务。

## 年度资料

在学习项目中打开「年度考纲与试卷」，选择「添加模拟资料」。平台会建立一份六个主题的模拟考纲和一份六题短卷，均为原创示例。可按主题开始学习并查看考纲覆盖；也可按题号和分值开启整卷练习或模考。客观题按卷面分值汇总，分析题只提供单列的 AI 训练反馈。

「导入年度资料」提供 JSON 格式模板。私有导入保留年度、版本、来源名称和链接。考纲必须与项目年份一致；真题可为目标年度或更早年度。真题正文和答案由导入者核对，平台目前未预置正式真题或官方考纲全文。官方书目单独列出，例如[高等教育出版社 2027 年大纲书目](https://www.hep.com.cn/book/show/2104375928531001345)。示例题和导入者提供的真题均不标为平台认证试卷。

## 检索与引用

「课程与资料」可搜索当前项目中授权资料的全部提取文本。检索支持中文双字词和英文关键词；助教只收到排序后的相关片段。当前采用平台侧词法检索，没有接入 DeepTutor 原生知识库或向量语义索引。扫描 PDF 需先 OCR。

引用核对须同时通过项目权限、资料版本和原文连续字符匹配。定位返回行号、版本摘要和上下文；本机上传的文字型 PDF 可以从引用打开原件对应页。可定位引文证明该文字存在，不能单独证明 AI 答复的推论正确。撤权后，旧运行和原文接口均拒绝访问。

## 启动和检查

在 Docker Desktop 已启动且项目依赖就绪时：

```powershell
npm --prefix frontend run build
powershell -ExecutionPolicy Bypass -File scripts/setup-v2.ps1 -Release
powershell -ExecutionPolicy Bypass -File scripts/start-release-v2.ps1
powershell -ExecutionPolicy Bypass -File scripts/status.ps1 -RuntimeName services-v2-release
```

已配置且运行中的 DeepTutor 可以用 `setup-v2.ps1 -Release -SkipTutor` 保留原配置。入口由 API 同源服务生产构建产物，不运行 Vite 开发服务器。业务状态看 `/health/ready`，DeepTutor 运行状态看 `/health/ai`。后者不调用付费模型，也不能替代真实模型验收。启动脚本发现端口被占用时退出，不接管其他应用进程。

本机服务分别运行传统任务、AI 和期限维护进程。即使浏览器离线，模考仍按最后成功保存的草稿到时交卷。AI 连接中断且已有下游运行 ID 时按事件序号重新订阅；进程被杀且执行结果不明时不会盲目再次提交。日志可按项目、测评和运行 ID 排查；仍未提供跨进程下游运行自动接管、逐调用计费报表或物理撤权清理作业。

## 备份与恢复

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backup-v2.ps1 -Release
.venv\Scripts\python.exe scripts/snapshot-v2.py validate <备份目录>
.venv\Scripts\python.exe scripts/snapshot-v2.py restore <备份目录> --destination <全新目录> --database-name zhixing_v2_restore_<名称>
```

协调备份短暂停止本项目写入和 DeepTutor；备份目录含私有配置，恢复只写全新数据库和目录。遇到发布故障时保留新库、新资料及快照，修复后再启动 5183；不将新版开始接收后的业务写入回退到旧库。

## 2026-11-05 验收

| 检查 | 结果 |
| --- | --- |
| 发布入口 | 5183 首页及项目深链接 HTTP 200；数据库迁移版本 `75d08ac3af22`；业务与 DeepTutor 健康检查通过 |
| 后端 | 82 项全量测试、15 项独立 PostgreSQL 测试通过 |
| 前端 | 生产构建、6 项 API 客户端测试、4 条浏览器流程通过 |
| 真实模型 | 使用隔离验收库从第 12,000 字以后命中并核对引文；两轮出题、独立校验、补学和复习安排通过 |
| 隔离与中断 | 其他用户无法读取引用；撤权后旧运行与原文不可读；断线后按同一运行重订阅；浏览器离线仍由服务端到时交卷 |
| 备份与恢复 | 发布库协调备份通过完整性校验，并恢复到独立数据库和目录；核对迁移版本及考研政治科目，未覆盖发布库 |
