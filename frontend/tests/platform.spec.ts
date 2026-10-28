import { test, expect, request as requests, type APIRequestContext, type Page } from '@playwright/test';
import fs from 'node:fs';

let teacherApi:APIRequestContext;
const tokens=new Map<APIRequestContext,string>();
async function login(page:Page,username:string) {
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill(username);
  await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
  await page.getByRole('button',{name:'进入工作台'}).click();
  await expect(page.getByRole('button',{name:'退出登录'})).toBeVisible();
}
async function data(client:APIRequestContext,path:string,method='GET',body?:unknown) {
  const r=await client.fetch('http://127.0.0.1:8001/api/v1'+path,{method,data:body,headers:{'Idempotency-Key':crypto.randomUUID(),'X-CSRF-Token':tokens.get(client)??''}});
  expect(r.ok(),await r.text()).toBeTruthy();
  return (await r.json()).data;
}

test.describe.serial('完整学习、评价与内容闭环',()=>{
  test.beforeAll(async()=>{
    teacherApi=await requests.newContext();
    await data(teacherApi,'/auth/login','POST',{username:'teacher',password:'Zhixing2026!'});
    const me=await data(teacherApi,'/me');
    tokens.set(teacherApi,me.csrf_token);
  });
  test.afterAll(async()=>{await teacherApi?.dispose()});

  test('教师核对并发布示例内容',async({page})=>{
    await login(page,'teacher');
    await page.getByRole('link',{name:'教学内容',exact:true}).click();
    await page.getByRole('link',{name:'原创示例讲义 · 实践与认识',exact:true}).click();
    await expect(page.getByRole('heading',{name:'资料原文',exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'关联知识卡',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'提交审核',exact:true}).click();
    await page.getByRole('textbox',{name:'审核说明'}).fill('浏览器测试：已核对原创正文、知识卡、题目与评分要点。');
    await page.getByRole('dialog').getByRole('button',{name:'提交审核',exact:true}).click();
    await expect(page.getByRole('button',{name:'审核确认并发布',exact:true})).toBeVisible({timeout:45000});
    await page.getByRole('button',{name:'审核确认并发布',exact:true}).click();
    await page.getByRole('textbox',{name:'审核说明'}).fill('测试教师确认发布，仅限隔离测试数据库。');
    await page.getByRole('dialog').getByRole('button',{name:'确认发布',exact:true}).click();
    await expect(page.getByRole('button',{name:'创建修订版本',exact:true})).toBeVisible();
    // The remaining fixtures use the exact same real publish API.
    const sources=await data(teacherApi,'/content/sources');
    for(const source of sources.items.filter((s:{status:string})=>s.status==='draft')) {
      await data(teacherApi,`/content/sources/${source.id}/submit`,'POST',{note:'测试内容核对'});
      await data(teacherApi,`/content/sources/${source.id}/publish`,'POST',{note:'隔离环境教师发布'});
    }
  });

  test('学生设置目标、完成诊断并恢复作答',async({page})=>{
    test.setTimeout(90000);
    await login(page,'student');
    await page.getByRole('link',{name:'目标与安排',exact:true}).click();
    await page.getByLabel('目标分数',{exact:true}).fill('78');
    await page.getByRole('button',{name:'保存并前往诊断'}).click();
    await page.getByRole('button',{name:'开始基础诊断',exact:true}).click();
    await expect(page.getByRole('heading',{name:'诊断进行中'})).toBeVisible();
    for(let i=0;i<6;i++) {
      await page.getByRole('link',{name:'开始学习'}).first().click();
      await expect(page.getByRole('heading',{name:'独立完成诊断'})).toBeVisible();
      const inputs=page.locator('input[type="radio"],input[type="checkbox"]');
      await inputs.first().check();
      await page.getByRole('textbox',{name:'思考过程',exact:true}).fill('诊断原始过程：根据材料判断。');
      await page.getByRole('button',{name:'保存草稿',exact:true}).click();
      await expect(page.getByText('已保存到服务器',{exact:true})).toBeVisible();
      if(i===0){await page.reload();await expect(page.getByRole('textbox',{name:'思考过程',exact:true})).toHaveValue('诊断原始过程：根据材料判断。')}
      await page.getByRole('button',{name:'提交作答',exact:true}).click();
      await expect(page.getByText('作答记录已保存',{exact:true})).toBeVisible();
      await expect(page.getByRole('heading',{name:'审核解析',exact:true})).toHaveCount(0);
      await page.getByRole('link',{name:'返回任务',exact:true}).click();
      await expect(page.getByRole('link',{name:'查看记录',exact:true})).toHaveCount(i+1);
    }
    await page.getByRole('button',{name:'结束诊断并生成学习安排'}).click();
    await expect(page.getByRole('heading',{name:'诊断已完成',exact:true})).toBeVisible();
    await page.getByRole('link',{name:'查看学习任务',exact:true}).click();
    await expect(page.getByRole('heading',{name:'今日学习任务',exact:true})).toBeVisible();
    await expect(page.locator('.ant-message-notice')).toHaveCount(0);
    await page.screenshot({path:'../docs/screenshots/student-home.png',fullPage:true});
    await page.getByRole('button',{name:'退出登录'}).click();
    await expect(page.getByRole('button',{name:'进入工作台'})).toBeVisible();
    await login(page,'student');
    await expect(page.getByText('每日 30 分钟 · 2027 年目标 · 目标 78 分',{exact:true})).toBeVisible();
  });

  test('补学、真实来源与新题验证',async({page})=>{
    await login(page,'student');
    await page.getByRole('link',{name:'错题与补学',exact:true}).click();
    const card=page.locator('.remediation-list > .ant-card').first();
    await expect(card).toBeVisible();
    await card.locator('.ant-select').click();
    await page.getByText('概念混淆',{exact:true}).last().click();
    await card.getByRole('button',{name:'我已阅读并理解'}).click();
    await expect(card.getByRole('button',{name:'3. 开始新题验证'})).toBeVisible();
    const sourceUrl=await card.getByRole('link',{name:'查看原文出处'}).getAttribute('href');
    await card.getByRole('link',{name:'查看原文出处'}).click();
    await expect(page.getByRole('heading',{name:'资料原文',exact:true})).toBeVisible();
    await expect(page.getByText('章节与段落定位，不提供虚构页码。正文摘要用于版本核对。')).toBeVisible();
    await page.getByRole('link',{name:'返回补学'}).click();
    await page.locator('.remediation-list > .ant-card').first().getByRole('button',{name:'3. 开始新题验证'}).click();
    await expect(page.getByRole('heading',{name:'补学后的新题验证'})).toBeVisible();
    const source=await data(teacherApi,'/sources/versions/'+sourceUrl!.split('/').pop());
    const prompt=await page.locator('.question-prompt').innerText();
    const question=source.questions.find((q:{prompt:string})=>q.prompt===prompt);
    expect(question).toBeTruthy();
    for(const answer of question.answer)await page.locator(`input[value="${answer}"]`).check();
    await page.getByRole('button',{name:'提交作答',exact:true}).click();
    await expect(page.getByRole('heading',{name:'本次评价',exact:true})).toBeVisible();
    await page.getByRole('link',{name:'复习计划',exact:true}).click();
    await expect(page.locator('.ant-table-tbody').getByText('第 1 阶段').first()).toBeVisible();
  });

  test('分析题人工评分、学生异议和教师修订',async({page})=>{
    const learner=await requests.newContext();
    await data(learner,'/auth/login','POST',{username:'student',password:'Zhixing2026!'});
    const me=await data(learner,'/me');tokens.set(learner,me.csrf_token);
    const plan=await data(learner,'/plans/today');
    const essay=plan.all_tasks.find((t:{kind:string})=>t.kind==='essay');
    await login(page,'student');await page.goto('/study/'+essay.id);
    await page.getByRole('textbox',{name:'你的材料分析',exact:true}).fill('调查和实践为认识提供来源。方案调整后，应根据实践反馈继续完善认识，并注意材料的具体条件。');
    await page.getByRole('textbox',{name:'思考过程',exact:true}).fill('先阐述原理，再对应材料，最后说明结论边界。');
    await page.getByRole('button',{name:'提交作答',exact:true}).click();
    await expect(page.getByText('分析题已提交，等待教师评分',{exact:true})).toBeVisible();
    const attempt=(await data(learner,'/attempt-history')).find((a:{task:{id:string}})=>a.task.id===essay.id);
    await page.getByRole('button',{name:'退出登录'}).click();await login(page,'teacher');
    await page.goto('/teacher/attempts/'+attempt.id);
    const scoreInputs=page.locator('input[role="spinbutton"]');
    await scoreInputs.nth(0).fill('3');await scoreInputs.nth(1).fill('4');
    await page.getByLabel('评语与依据',{exact:true}).fill('原理基本准确，材料分析需要更充分。');
    await page.getByRole('button',{name:'保存正式评分'}).click();
    await expect(page.getByText('当前有效评价：7 / 10 分 · 第 1 次评价',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'退出登录'}).click();await login(page,'student');
    await page.goto('/study/'+essay.id);
    await page.getByRole('button',{name:'对评价有异议？'}).click();
    await page.getByRole('textbox',{name:'异议说明',exact:true}).fill('我在后半段结合了材料条件，请再次核对。');
    await page.getByRole('dialog').getByRole('button',{name:'提交异议',exact:true}).click();
    await expect(page.getByText('已提交教师复核',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'退出登录'}).click();await login(page,'teacher');
    await page.getByRole('link',{name:'评价复核',exact:true}).click();
    await page.getByRole('link',{name:'进入复核',exact:true}).click();
    await page.locator('input[role="spinbutton"]').nth(0).fill('4');await page.locator('input[role="spinbutton"]').nth(1).fill('6');
    await page.getByLabel('复核说明与修改原因',{exact:true}).fill('重新核对，材料分析已覆盖评分要点，修订为满分。');
    await page.getByRole('button',{name:'保存复核结果'}).click();
    await expect(page.getByText('已处理',{exact:true})).toBeVisible();
    await learner.dispose();
  });

  test('教师新增资料、知识卡、题目并创建修订版本',async({page})=>{
    await login(page,'teacher');
    await page.getByRole('link',{name:'教学内容',exact:true}).click();
    await page.getByRole('button',{name:'导入新资料',exact:true}).click();
    const dialog=page.getByRole('dialog');
    await dialog.getByLabel('资料名称',{exact:true}).fill('原创浏览器核对资料');
    await dialog.getByLabel('原文正文',{exact:true}).fill('# 实践与认识补充\n\n实践为认识提供来源，结论需要结合具体条件。');
    await dialog.getByLabel('对应知识点',{exact:true}).click();
    await page.getByRole('option',{name:'实践与认识',exact:true}).click();
    await dialog.getByRole('button',{name:'保存为草稿',exact:true}).click();
    await expect(page.getByRole('heading',{name:'原创浏览器核对资料',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'添加知识卡',exact:true}).click();
    await page.getByRole('dialog').getByLabel('卡片标题',{exact:true}).fill('概念回看');
    await page.getByRole('dialog').getByLabel('知识卡内容',{exact:true}).fill('区分认识来源、发展和检验，结合具体条件分析。');
    await page.getByRole('dialog').getByRole('button',{name:'保存知识卡',exact:true}).click();
    await expect(page.getByRole('heading',{name:'概念回看',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'添加题目',exact:true}).click();
    const question=page.getByRole('dialog');
    await question.getByLabel('题干或材料',{exact:true}).fill('下列哪项是认识的来源？');
    await question.getByLabel('选项 A',{exact:true}).fill('实践');
    await question.getByLabel('选项 B',{exact:true}).fill('脱离现实的猜测');
    await question.getByRole('checkbox',{name:'A',exact:true}).check();
    await question.getByLabel('审核解析',{exact:true}).fill('依据正文，实践为认识提供来源。');
    for(const [i,label] of ['相关概念','突破口','分步引导','完整解析'].entries())await question.getByLabel(`${i+1}. ${label}`,{exact:true}).fill(`第 ${i+1} 级审核提示：阅读正文并识别认识来源。`);
    await question.getByRole('button',{name:'保存题目',exact:true}).click();
    await expect(page.getByText('单选题 · 下列哪项是认识的来源？',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'提交审核',exact:true}).click();
    await page.getByRole('textbox',{name:'审核说明',exact:true}).fill('已核对原文、知识卡及答案。');
    await page.getByRole('dialog').getByRole('button',{name:'提交审核',exact:true}).click();
    await page.getByRole('button',{name:'审核确认并发布',exact:true}).click();
    await page.getByRole('textbox',{name:'审核说明',exact:true}).fill('确认本隔离环境资料可用于测试。');
    await page.getByRole('dialog').getByRole('button',{name:'确认发布',exact:true}).click();
    await page.getByRole('button',{name:'创建修订版本',exact:true}).click();
    await expect(page.getByText('版本 2',{exact:true})).toBeVisible();
    const original=await page.getByRole('textbox',{name:'资料原文正文',exact:true}).inputValue();
    await page.getByRole('textbox',{name:'资料原文正文',exact:true}).fill(original+'\n\n修订说明：保留适用范围。');
    await page.getByRole('button',{name:'保存正文',exact:true}).click();
    await expect(page.getByText('正文已保存',{exact:true})).toBeVisible();
  });

  test('手机布局无横向溢出',async({page})=>{
    await page.setViewportSize({width:390,height:844});
    await login(page,'student');
    await expect(page.getByRole('heading',{name:'林同学，今天也向前一步'})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
    await page.getByRole('button',{name:'展开菜单'}).click();
    await page.getByRole('link',{name:'复习计划',exact:true}).click();
    await expect(page.getByRole('heading',{name:'复习计划',exact:true})).toBeVisible();
    await expect(page.locator('.sidebar')).not.toBeInViewport();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
    await page.screenshot({path:'../docs/screenshots/mobile-reviews.png',fullPage:true});
  });
});
