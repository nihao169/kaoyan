# 教师资料与 Agent 流程（2026-10-29）

本说明更新旧架构中“目标—基础诊断—审核发布”的主流程；旧接口和记录用于兼容历史。

## 数据与责任

`source_activations`记录原文启用，`source_knowledge`将资料版本与多个机构知识点关联。原文件、固定版式PDF、页块及引用保留。Agent只检索当前资料与教师选择的已启用补充资料，不用模型记忆作为出处。

`agent_runs`记录输入、阶段、模型、工作流版本、用量和结果；`artifact_evidence`绑定知识卡、题目与逐字原文。LangGraph检查点保存在`data/workflows.db`，业务任务由`jobs`领取及续租。生成后先执行结构、题型、答案、引文和重复校验，再独立模型校验；最多两轮修正。失败结果不发布，显式重试启动新的有限修正周期，异常中断恢复已有检查点。

提取阶段最多抽取16个代表页段，每段最多1800字，按知识点再进行混合检索。页面展示本批覆盖说明。1000页是上传限制，不是承诺完整理解或覆盖1000页。

`generated_questions`区分全班可用题与学生个人题；后者不出现在教师公共题库、资料题目列表，也不在进度接口中提前返回答案。教师编辑生成题会创建新版本，旧版本停用但保留。

`assignments`固定题目版本ID，`assignment_submissions`和`assignment_tasks`保存整组作答。保存草稿仍使用带修订号的旧接口；单题提交被阻止，整组先检查所有题目，再原子冻结与判分。发布与提交都校验班级授权和幂等性。

客观题由既有规则按固定答案判分。分析题生成`evaluation_suggestions`，只有教师确认或修改后才写入正式`evaluations`及修订；初评不产生正式错题、独立掌握或总分证据。旧规则评分仍显示系统来源，不改称教师评分。

错题诊断及针对性出题分别由学生手动触发，不在提交时自动调用。`targeted_practices`、`practice_tasks`归当前学生所有，保留原作答关联。新作答再次独立正确才进入原有复习安排，阅读建议本身不是掌握证据。教师可在学习链路查看个人练习与相关复习记录。

## 主要接口

| 接口 | 用途 |
| --- | --- |
| GET /content/sources/{version}/processing | 解析、章节、启用与生成状态 |
| POST /content/sources/{version}/enable | 一次启用并生成，重复请求复用任务 |
| POST /content/sources/{version}/generate | 另生成一批（带幂等键） |
| GET /agent-runs/{id}，POST /agent-runs/{id}/retry | 恢复进度、失败重试 |
| GET /teaching/questions | 已校验的公共生成题库 |
| POST /teacher/assignments | 一次发布班级作业 |
| GET /assignments，POST /assignments/{id}/start、/submit | 学生列表、草稿组、整组提交 |
| GET /mistake-diagnoses | 完整原题、选项差异、原始过程和原文 |
| POST /remediations/{id}/diagnose、/practice-generations | 手动诊断、手动针对性出题 |
| POST /practice-groups/{id}/open、/submit | 个人练习及统一提交 |
| POST /teacher/attempts/{id}/confirm-ai-evaluation | 确认或修改AI初评分项 |

完整字段以`docs/openapi.json`及前端生成类型为准。用户、机构、班级、资料访问和最终成绩由业务代码控制，不由模型执行。长模型调用期间释放业务数据库事务，交付前再次核对权限、成员状态和来源状态。

迁移`40727c9291fc`只增加结构、归档活动中的旧入门诊断，不清空账号、作答、评分或来源版本。现有演示题保留原标识，不作为新Agent出题验收证据。
