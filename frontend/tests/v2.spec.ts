import { test,expect } from '@playwright/test';

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
  await expect(page.getByRole('button',{name:'确认学习背景',exact:true})).toBeVisible();
});

test('年度模拟资源、全文命中与原文核对',async({page})=>{
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill('student');
  await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
  await page.getByRole('button',{name:'进入工作台'}).click();
  await page.getByRole('link',{name:'学习项目',exact:true}).click();
  await page.getByRole('button',{name:'新建项目',exact:true}).click();
  await page.getByRole('radio',{name:/考研学习/}).check();
  await page.getByRole('button',{name:'创建新项目'}).click();
  await page.getByLabel('项目名称').fill('年度资料验收');
  await page.getByLabel('课程名称',{exact:true}).fill('考研政治');
  await page.getByRole('button',{name:'创建并与助教开始学习'}).click();
  await page.getByRole('tab',{name:'年度考纲与试卷'}).click();
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
