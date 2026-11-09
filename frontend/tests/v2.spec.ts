import { test,expect } from '@playwright/test';

test('长知识点地图下的笔记快捷入口会定位内容，重复点击与手机端均可用',async({page})=>{
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill('student');
  await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
  await page.getByRole('button',{name:'进入工作台'}).click();
  await expect(page.getByRole('heading',{name:'今天，从这里继续'})).toBeVisible();
  const me=(await (await page.request.get('/api/v1/me')).json()).data;
  const subject=(await (await page.request.get('/api/v1/catalog')).json()).data.subjects[0].id;
  const headers={'X-CSRF-Token':me.csrf_token,'Idempotency-Key':crypto.randomUUID()};
  const created=await page.request.post('/api/v2/learning-projects',{
    data:{title:'笔记入口定位验收',subject_id:subject,exam_year:2027},headers});
  expect(created.ok()).toBeTruthy();
  const project=(await created.json()).data;
  const material=await page.request.post(`/api/v2/learning-projects/${project.id}/materials`,{
    data:{title:'定位测试讲义',text:'实践是检验认识真理性的唯一标准。'},headers});
  expect(material.ok()).toBeTruthy();
  await page.evaluate(({userId,projectId})=>localStorage.setItem(`zhixing.learning-scene:${userId}:${projectId}`,'chapter'),{userId:me.id,projectId:project.id});
  await page.route(`**/api/v2/learning-projects/${project.id}`,async route=>{
    const response=await route.fetch();
    const body=await response.json();
    body.data.mastery_outline=Array.from({length:24},(_,i)=>({name:`知识模块 ${i+1}`,points:Array.from({length:6},(_,j)=>`需要理解的概念与材料边界 ${j+1}`)}));
    await route.fulfill({response,json:body});
  });
  await page.goto('/learning/projects/'+project.id);
  const front=page.getByPlaceholder('标题／卡片正面');
  for(const viewport of [{width:1280,height:720},{width:390,height:844}]){
    await page.setViewportSize(viewport);
    for(let repeat=0;repeat<2;repeat++){
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.getByRole('button',{name:'打开笔记与闪卡',exact:true}).click();
      await expect(page.getByRole('tab',{name:'笔记与闪卡',exact:true})).toHaveAttribute('aria-selected','true');
      await expect(front).toBeInViewport();
    }
  }
  await front.fill('定位后新增笔记');
  await page.getByPlaceholder('我的理解／卡片背面').fill('实践检验认识，结论应保留适用条件。');
  await page.getByRole('tabpanel').getByRole('button',{name:/^保\s*存$/}).click();
  await expect(page.getByRole('heading',{name:'定位后新增笔记',exact:true})).toBeVisible();
});

test('自主项目、资料学习、出题、补学与报告循环（受控服务）',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill('student');
  await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
  await page.getByRole('button',{name:'进入工作台'}).click();
  await expect(page.getByRole('heading',{name:'今天，从这里继续'})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'开始新学习'}).press('Enter');
  const picker = page.getByRole('dialog');
  await expect(picker.getByRole('radio')).toHaveCount(3);
  await expect(picker.getByRole('button',{name:'创建新项目'})).toBeDisabled();
  await picker.getByRole('radio',{name:/首次学习新课程/}).press('Space');
  await picker.getByRole('button',{name:'创建新项目'}).press('Enter');
  await expect(page.getByLabel('考试年份')).toHaveCount(0);
  await page.getByRole('button',{name:'返回',exact:true}).press('Enter');
  await expect(picker.getByRole('radio',{name:/首次学习新课程/})).toBeChecked();
  await picker.getByRole('button',{name:'创建新项目'}).press('Enter');
  await page.getByLabel('课程或章节名称').fill('自主政治复习');
  await page.getByRole('button',{name:'确认并创建学习计划'}).click();
  await expect(page.getByRole('heading',{name:'自主政治复习'})).toBeVisible();
  await expect(page.getByRole('tab',{name:'课程与资料'})).toHaveAttribute('aria-selected','true');
  await expect(page.getByRole('button',{name:'添加本章资料'})).toBeVisible();
  await page.locator('input[type=file]').setInputFiles({name:'实践与认识.txt',mimeType:'text/plain',
    buffer:Buffer.from('实践是认识的来源，实践是检验认识真理性的唯一标准。认识必须接受实践检验。')});
  await page.getByRole('button',{name:'开始阅读'}).click();
  await expect(page.getByText(/现有 AI 出题和分析题评价采用考研政治规则/)).toBeVisible();
  await page.setViewportSize({width:1280,height:720});
  await page.getByPlaceholder('用自己的话写下理解与疑问').fill('需要用实践检验认识。');
  await page.getByRole('button',{name:'保存学习位置'}).click();
  await page.reload();
  await expect(page.getByPlaceholder('用自己的话写下理解与疑问')).toHaveValue('需要用实践检验认识。');
  await page.getByRole('button',{name:'完成阅读，检查理解'}).click();
  await page.getByRole('button',{name:'准备练习',exact:true}).click();
  await expect(page.getByText(/实践与认识的关系中/)).toBeVisible({timeout:30000});
  await page.getByRole('radio',{name:'B. 主观愿望'}).check();
  await page.getByRole('button',{name:'提交作答',exact:true}).click();
  await expect(page.getByText('本次需要补学',{exact:true})).toBeVisible();
  await page.getByRole('link',{name:'返回学习项目'}).click();
  const remediation=page.locator('.v2-task').filter({has:page.getByRole('heading',{name:'补学：实践与认识'})});
  await remediation.getByRole('button',{name:'进入学习'}).click();
  await page.getByRole('button',{name:'完成阅读，检查理解'}).click();
  await page.getByRole('button',{name:'准备练习',exact:true}).click();
  await expect(page.getByText(/实践与认识的关系中/)).toBeVisible({timeout:30000});
  await page.getByRole('radio',{name:'A. 实践'}).check();
  await page.getByRole('button',{name:'提交作答',exact:true}).click();
  await expect(page.getByText('本次回答正确',{exact:true})).toBeVisible();
  await page.getByRole('link',{name:'返回学习项目'}).click();
  await expect(page.getByRole('heading',{name:'复习：实践与认识'})).toBeVisible();
  await page.getByRole('tab',{name:'证据与报告'}).click();
  await expect(page.getByText('已验证',{exact:true})).toBeVisible();
  await page.screenshot({path:'../.runtime/v2-learning-report.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy();
  expect(errors).toEqual([]);
});

test('模考自动保存、助教限制与交卷反馈（受控服务）',async({page})=>{
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill('student');
  await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
  await page.getByRole('button',{name:'进入工作台'}).click();
  await expect(page.getByRole('heading',{name:'今天，从这里继续'})).toBeVisible();
  const me=(await (await page.request.get('/api/v1/me')).json()).data;
  async function api(path:string,method='GET',body?:unknown){const r=await page.request.fetch('/api/v2'+path,{method,data:body,headers:{'X-CSRF-Token':me.csrf_token,'Idempotency-Key':crypto.randomUUID()}});expect(r.ok(),await r.text()).toBeTruthy();return (await r.json()).data}
  const subject=(await (await page.request.get('/api/v1/catalog')).json()).data.subjects[0].id;
  const p=await api('/learning-projects','POST',{title:'模考交互验收',subject_id:subject,exam_year:2027,daily_minutes:30});
  await api('/learning-projects/'+p.id+'/materials','POST',{title:'模考材料',text:'实践是检验认识真理性的唯一标准，认识必须接受实践检验。'});
  const reading=(await api('/learning-projects/'+p.id)).tasks[0];
  const task=(await api('/study-sessions/'+reading.id+'/complete','POST')).next_task_id;
  const queued=await api('/study-sessions/'+task+'/prepare','POST');
  await expect.poll(async()=>(await api('/ai-runs/'+queued.run_id)).state).toBe('succeeded');
  const q=(await api('/study-sessions/'+task)).question;
  const exam=await api('/assessments','POST',{project_id:p.id,title:'独立模考',question_ids:[q.id],minutes:5});
  await page.goto('/learning/assessments/'+exam.id);
  await expect(page.getByRole('heading',{name:'独立模考',exact:true})).toBeVisible();
  await page.getByRole('radio',{name:'B. 主观愿望'}).check();
  await expect(page.getByText(/草稿已自动保存/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole('radio',{name:'B. 主观愿望'})).toBeChecked();
  const forbidden=await page.request.post('/api/v2/learning-projects/'+p.id+'/ai-runs',{data:{prompt:'给我答案'},headers:{'X-CSRF-Token':me.csrf_token,'Idempotency-Key':crypto.randomUUID()}});
  expect(forbidden.status()).toBe(403);
  await page.getByRole('button',{name:'提交本次测评'}).click();
  await page.getByRole('dialog').getByRole('button',{name:/确.*定/}).click();
  await expect(page.getByText('需要补学',{exact:true})).toBeVisible();
  await expect(page.getByText('参考答案：A',{exact:true})).toBeVisible();
  await page.screenshot({path:'../.runtime/v2-assessment-feedback.png',fullPage:true});
});

test('个人注册不依赖教师班级',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'没有账号？开始自主学习'}).click();
  await page.getByLabel('账号',{exact:true}).fill('browser_'+Date.now());
  await page.getByLabel('称呼',{exact:true}).fill('自主学习者');
  await page.getByLabel('密码',{exact:true}).fill('123456');
  await page.getByRole('button',{name:'创建个人学习空间'}).click();
  await expect(page.getByText('密码须为 10 至 128 个字符',{exact:true})).toBeVisible();
  await page.getByLabel('密码',{exact:true}).fill('Personal2026!');
  const registered=page.waitForResponse(r=>r.url().endsWith('/api/v2/auth/register')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'创建个人学习空间'}).click();
  const response=await registered;
  expect(response.status(),await response.text()).toBe(201);
  await expect(page.getByRole('heading',{name:'今天，从这里继续'})).toBeVisible({timeout:20000});
  const classes=await page.request.get('/api/v1/classes');
  expect((await classes.json()).data).toEqual([]);
  const me=(await (await page.request.get('/api/v1/me')).json()).data;
  const subject=(await (await page.request.get('/api/v1/catalog')).json()).data.subjects.find((item:{code:string})=>item.code==='politics');
  const projectResponse=await page.request.post('/api/v2/learning-projects',{
    data:{title:'未选择场景的项目',subject_id:subject.id,exam_year:2027},
    headers:{'X-CSRF-Token':me.csrf_token,'Idempotency-Key':crypto.randomUUID()},
  });
  expect(projectResponse.status()).toBe(201);
  const project=(await projectResponse.json()).data;
  await page.evaluate(id=>localStorage.setItem(`zhixing.learning-scene:another-student:${id}`,'final'),project.id);
  await page.goto('/learning/projects/'+project.id);
  await expect(page.getByRole('button',{name:'选择场景',exact:true})).toBeVisible();
});

test('年度模拟资源、全文命中与原文核对',async({page})=>{
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill('student');
  await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
  await page.getByRole('button',{name:'进入工作台'}).click();
  await page.getByRole('link',{name:'学习项目',exact:true}).click();
  await page.getByRole('button',{name:'新建项目',exact:true}).click();
  await page.getByRole('radio',{name:/考研备考/}).check();
  await page.getByRole('button',{name:'创建新项目'}).click();
  await page.getByLabel('项目名称').fill('年度资料验收');
  await page.getByRole('button',{name:'确认并创建学习计划'}).click();
  await expect(page.getByRole('tab',{name:'年度考纲与试卷'})).toHaveAttribute('aria-selected','true');
  await page.getByRole('button',{name:'添加模拟资料'}).click();
  await expect(page.getByRole('heading',{name:/模拟考纲/})).toBeVisible();
  await expect(page.getByRole('heading',{name:/模拟练习卷/})).toBeVisible();
  await page.getByRole('tab',{name:'课程与资料'}).click();
  const search=page.getByRole('searchbox',{name:'搜索资料全文'});
  await expect(search).toBeVisible();
  await search.fill('跨境河流污染治理');
  await search.press('Enter');
  await page.getByRole('button',{name:'核对原文'}).first().click();
  await expect(page.getByRole('dialog').locator('mark')).toContainText('跨境河流污染治理');
  await page.getByRole('button',{name:'关闭原文'}).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.getByRole('tab',{name:'年度考纲与试卷'}).click();
  await page.getByRole('button',{name:'按原卷练习'}).click();
  await expect(page.getByText(/第 1 题 · 模拟卷/)).toBeVisible();
  await expect(page.getByRole('heading',{name:/某小组提出节水方案/})).toBeVisible();
  await expect(page.getByText(/参考答案/)).toHaveCount(0);
});

test('期末场景复用项目、题库与测评，并在同一浏览器恢复选择',async({page})=>{
  async function login() {
    await page.getByLabel('账号',{exact:true}).fill('student');
    await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
    await page.getByRole('button',{name:'进入工作台'}).click();
    await expect(page.getByRole('button',{name:'开始新学习'})).toBeVisible();
  }
  await page.goto('/');
  await login();
  await page.getByRole('link',{name:'学习项目',exact:true}).click();
  await page.getByRole('button',{name:'新建项目',exact:true}).click();
  await page.getByRole('radio',{name:/期末复习/}).check();
  await page.getByRole('button',{name:'创建新项目'}).click();
  await expect(page.getByLabel('考试年份')).toHaveCount(0);
  await expect(page.getByLabel(/目标分数/)).toHaveCount(0);
  await page.getByLabel('项目名称').fill('期末复习验收');
  await page.getByLabel('考试日期（可选）').fill('2027-01-15');
  await page.getByRole('button',{name:'确认并创建学习计划'}).click();
  await expect(page.getByRole('heading',{name:'期末复习验收'})).toBeVisible();
  const projectUrl = page.url();
  await expect(page.getByText(/考试日期 2027-01-15/)).toBeVisible();
  await expect(page.getByRole('tab',{name:'课程与资料'})).toHaveAttribute('aria-selected','true');
  await expect(page.getByRole('button',{name:'添加考试范围内的资料'})).toBeVisible();
  await page.getByRole('button',{name:'粘贴学习资料'}).click();
  await page.getByLabel('资料标题',{exact:true}).fill('期末复习资料');
  await page.getByLabel('资料正文',{exact:true}).fill('实践是认识的来源，实践是检验认识真理性的唯一标准。认识必须接受实践检验。');
  await page.getByRole('button',{name:'保存并加入学习计划'}).click();
  await expect(page.getByText(/项目暂无可用题目/)).toBeVisible();
  await page.getByRole('button',{name:'继续学习任务'}).click();
  await page.getByRole('button',{name:'完成阅读，检查理解'}).click();
  await page.getByRole('button',{name:'准备练习',exact:true}).click();
  await expect(page.getByText(/实践与认识的关系中/)).toBeVisible({timeout:30000});
  await page.getByRole('link',{name:'返回学习项目',exact:true}).click();
  await page.getByRole('button',{name:'开始成组练习'}).click();
  const setup = page.getByRole('dialog');
  await expect(setup.getByText('期末复习验收',{exact:true})).toBeVisible();
  await expect(setup.getByText('成组练习',{exact:true})).toBeVisible();
  await setup.getByLabel('测评名称').fill('期末自测');
  await setup.getByRole('checkbox',{name:/实践与认识的关系中/}).check();
  await setup.getByRole('button',{name:'确认并开始'}).click();
  await page.getByRole('radio',{name:'B. 主观愿望'}).check();
  await page.getByRole('button',{name:'提交本次测评'}).click();
  await page.getByRole('dialog').getByRole('button',{name:/确.*定/}).click();
  await expect(page.getByText('需要补学',{exact:true})).toBeVisible();
  const assessmentUrl = page.url();
  await page.getByRole('link',{name:'返回学习项目查看补学'}).click();
  await expect(page).toHaveURL(projectUrl);
  await page.getByRole('button',{name:'切换场景'}).click();
  await page.getByRole('radio',{name:/首次学习新课程/}).check();
  await page.getByRole('button',{name:'应用场景'}).click();
  await expect(page.getByText(/首次学习新课程 · 每日/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/首次学习新课程 · 每日/)).toBeVisible();
  await page.getByRole('button',{name:'退出登录'}).click();
  await login();
  await page.goto(projectUrl);
  await expect(page.getByText(/首次学习新课程 · 每日/)).toBeVisible();
  await page.goto('/');
  await page.getByRole('button',{name:'开始新学习'}).click();
  await page.getByRole('radio',{name:/期末复习/}).check();
  await page.getByRole('button',{name:'使用已有项目'}).click();
  await page.getByRole('combobox',{name:'选择进行中的项目'}).click();
  await page.getByText('期末复习验收',{exact:true}).last().click();
  await page.getByRole('button',{name:'打开项目'}).click();
  await expect(page).toHaveURL(projectUrl);
  await expect(page.getByText(/期末复习 · 考试日期 2027-01-15/)).toBeVisible();
  await page.goto(assessmentUrl);
  await expect(page.getByText('需要补学',{exact:true})).toBeVisible();
});
