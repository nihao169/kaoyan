import {test,expect,type Page} from '@playwright/test';

async function login(page:Page){
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill('student');
  await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
  await page.getByRole('button',{name:'进入工作台'}).click();
  await expect(page.getByRole('heading',{name:'今天，从这里继续'})).toBeVisible();
  const me=(await (await page.request.get('/api/v1/me')).json()).data;
  return async(path:string,method='GET',body?:unknown)=>{
    const response=await page.request.fetch('/api/v2'+path,{method,data:body,
      headers:{'X-CSRF-Token':me.csrf_token,'Idempotency-Key':crypto.randomUUID()}});
    expect(response.ok(),await response.text()).toBeTruthy();return (await response.json()).data;
  };
}

for(const [scene,label] of [['chapter','首次学习'],['final','期末复习'],['kaoyan','考研学习']]){
  test(`${label}的课程和场景保存在服务端，刷新后继续原生学习`,async({page})=>{
    await login(page);
    await page.getByRole('button',{name:'开始新学习'}).click();
    await page.getByRole('radio',{name:new RegExp(label)}).check();
    await page.getByRole('button',{name:'创建新项目'}).click();
    await page.getByLabel(scene==='chapter'?'课程或章节名称':'项目名称',{exact:true}).fill(label+'统计学');
    await page.getByLabel('课程名称',{exact:true}).fill('统计学');
    await page.getByRole('button',{name:'创建并准备资料'}).click();
    await expect(page.getByRole('tab',{name:'与助教学习',exact:true})).toHaveAttribute('aria-selected','true');
    await expect(page.getByRole('heading',{name:'准备资料'})).toBeVisible();
    await expect(page.getByRole('button',{name:scene==='final'?'生成复习范围':scene==='kaoyan'?'生成考纲学习路线':'生成学习大纲'})).toBeDisabled();
    const id=page.url().split('/').pop();
    const p=(await (await page.request.get('/api/v2/learning-projects/'+id)).json()).data;
    expect(p.scenario).toBe(scene);expect(p.course_name).toBe('统计学');expect(p.scene_confirmed).toBe(true);
    await page.evaluate(()=>localStorage.clear());await page.reload();
    await expect(page.getByRole('heading',{name:label+'统计学',exact:true})).toBeVisible();
  });
}

test('旧项目先确认学习背景，保存后不再依赖浏览器场景缓存',async({page})=>{
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'旧项目保留',exam_year:2027});
  await page.goto('/learning/projects/'+p.id);
  await expect(page.getByRole('heading',{name:'先确认这个项目怎样学习'})).toBeVisible();
  await page.getByRole('radio',{name:/期末复习/}).check();
  await page.getByLabel('课程名称',{exact:true}).fill('统计学');
  await page.getByRole('button',{name:'确认学习背景',exact:true}).click();
  await expect(page.getByRole('heading',{name:'准备资料'})).toBeVisible();
  expect((await api('/learning-projects/'+p.id)).scenario).toBe('final');
});

test('期末项目从已有讲义选择整份资料和章节',async({page})=>{
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'选择已有考试资料',course_name:'统计学',scenario:'final'});
  const base='/learning-projects/'+p.id;
  const notes=await api(base+'/materials','POST',{title:'课堂笔记',text:'关于总体、样本及估计的补充说明。'});
  const book=await api(base+'/materials','POST',{title:'统计讲义',text:'# 总体与样本\n抽样概念。\n\n# 参数估计\n估计方法。'});
  await page.goto('/learning/projects/'+p.id);
  await page.getByRole('button',{name:'确认考试范围',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'确认期末考试范围'});
  await dialog.getByRole('checkbox',{name:'课堂笔记'}).check();
  await dialog.getByText('选择章节',{exact:true}).click();
  await dialog.getByRole('checkbox',{name:'总体与样本'}).check();
  await dialog.getByRole('button',{name:'保存考试范围'}).click();
  await expect(dialog).toBeHidden();
  expect((await api(base+'/learning')).preparation.scope).toMatchObject({material_ids:[notes.id],
    sections:[{material_id:book.id,title:'总体与样本'}]});
});

test('考研项目从学习页和年度资料页直接上传教材',async({page})=>{
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'多份考研资料',course_name:'统计学',scenario:'kaoyan',exam_year:2027});
  await page.goto('/learning/projects/'+p.id);
  const upload=page.getByRole('button',{name:'导入教材或讲义',exact:true});
  const first=page.waitForEvent('filechooser');
  await upload.click();
  await (await first).setFiles({name:'抽样.txt',mimeType:'text/plain',buffer:Buffer.from('随机抽样需要明确总体和样本。')});
  await expect(page.getByRole('tab',{name:'与助教学习',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.getByRole('region',{name:'准备资料'})).toContainText('抽样.txt');
  await page.getByRole('tab',{name:'年度考纲与试卷'}).click();
  const second=page.waitForEvent('filechooser');
  await upload.click();
  await (await second).setFiles([
    {name:'估计.txt',mimeType:'text/plain',buffer:Buffer.from('估计值会随抽取的样本而变化。')},
    {name:'检验.txt',mimeType:'text/plain',buffer:Buffer.from('统计检验需要先明确零假设。')},
  ]);
  await expect(upload).toBeEnabled();
  await expect(page.getByRole('tab',{name:'年度考纲与试卷'})).toHaveAttribute('aria-selected','true');
  await page.getByRole('tab',{name:'课程与资料',exact:true}).click();
  await expect(page.getByText('估计.txt',{exact:true})).toBeVisible();
  await expect(page.getByText('检验.txt',{exact:true})).toBeVisible();
  await expect(page.getByText('抽样.txt',{exact:true})).toBeVisible();
});

test('考研项目在索引完成后自动更新准备状态',async({page})=>{
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'索引状态刷新',course_name:'统计学',scenario:'kaoyan',exam_year:2027});
  let ready=false;
  await page.route(`**/api/v2/learning-projects/${p.id}/learning`,route=>route.fulfill({json:{data:{
    state:ready?'not_started':'preparing',messages:[],question:null,
    preparation:{ready,papers:[],checks:[{id:'books',label:'教材或讲义',state:ready?'ready':'indexing',
      items:[{id:'book',title:'统计讲义',state:ready?'ready':'indexing',error:''}]}]},
    workflow:{steps:['准备资料','考纲学习路线'],step:ready?1:0,
      actions:ready?[{id:'kaoyan_outline',label:'生成考纲学习路线'}]:[]},
  }}}));
  await page.goto('/learning/projects/'+p.id);
  await expect(page.getByText('统计讲义 · 正在建立索引')).toBeVisible();
  ready=true;
  await expect(page.getByRole('button',{name:'生成考纲学习路线',exact:true})).toBeEnabled();
});

test('今日小结保留待答题，继续学习后可再次作答',async({page})=>{
  const api=await login(page);
  const project=await api('/learning-projects','POST',{title:'今日任务验收',course_name:'统计学',scenario:'chapter'});
  let status='active';
  const question={question_id:'q1',prompt:'什么是样本？',options:[]};
  await page.route(`**/api/v2/learning-projects/${project.id}/learning`,async route=>{
    if(route.request().method()==='POST'){
      const body=route.request().postDataJSON();
      status=body.action_id==='chapter_summary'?'paused':'active';
      return route.fulfill({json:{data:{continued:true}}});
    }
    await route.fulfill({json:{data:{state:'question',request_id:'q1',question,messages:[],
      daily_plan:{id:'day',date:'2026-11-14',budget:45,seconds:30,state:status,completed:0,question_id:'q1',
        items:[{id:'sample',name:'总体与样本',minutes:10}],last_question:true},
      workflow:{steps:['准备资料','学习大纲','讲解与理解检查','小结与复习'],step:2,actions:[]}}}});
  });
  await page.route('**/learning/activity',route=>route.fulfill({json:{data:{reached:false}}}));
  await page.goto('/learning/projects/'+project.id);
  await expect(page.getByRole('heading',{name:'最后一题'})).toBeVisible();
  const daily=page.locator('summary').filter({hasText:'今日任务'});
  await expect(page.getByText('总体与样本 · 10 分钟 · 待完成')).toBeHidden();
  const answer=page.locator('.native-question').getByRole('textbox');
  await answer.fill('总体的一部分');
  await daily.press('Enter');
  await expect(page.getByText('总体与样本 · 10 分钟 · 待完成')).toBeVisible();
  await daily.click();
  await expect(page.getByRole('button',{name:'查看学习小结'})).toBeHidden();
  await daily.click();
  await page.getByRole('button',{name:'查看学习小结'}).click();
  await expect(page.getByRole('dialog')).toContainText('尚未完成检查');
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await daily.click();
  await expect(page.getByRole('button',{name:'查看学习小结'})).toBeHidden();
  await expect(page.getByText('今日学习已暂停，继续学习后可作答。')).toBeVisible();
  await expect(answer).toBeDisabled();
  await expect(page.getByRole('button',{name:'提交回答'})).toBeDisabled();
  await page.getByRole('button',{name:'继续学习',exact:true}).click();
  await expect(answer).toBeEnabled();
  await expect(page.getByRole('button',{name:'提交回答'})).toBeEnabled();
  await expect(answer).toHaveValue('总体的一部分');
});

test('索引失败时仍显示已有学习现场',async({page})=>{
  const api=await login(page);
  const project=await api('/learning-projects','POST',{title:'已有学习现场',course_name:'统计学',scenario:'chapter'});
  await page.route(`**/api/v2/learning-projects/${project.id}/learning`,route=>route.fulfill({json:{data:{
    state:'question',writable:false,request_id:'saved',question:{question_id:'saved',prompt:'什么是样本？',options:[]},
    messages:[{role:'assistant',content:'已保存的统计学讲解'}],
    preparation:{ready:false,checks:[{id:'books',label:'本章教材或讲义',state:'failed',
      items:[{id:'book',title:'统计学讲义',state:'failed',error:'索引失败'}]}]},
  }}}));
  await page.goto('/learning/projects/'+project.id);
  await expect(page.getByRole('button',{name:'准备或重试索引'})).toBeEnabled();
  await expect(page.getByText('已保存的统计学讲解')).toBeVisible();
  await expect(page.getByText('什么是样本？')).toBeVisible();
  await expect(page.getByText('学习资料尚未就绪，暂时不能作答。')).toBeVisible();
  await expect(page.getByRole('button',{name:'提交回答'})).toBeDisabled();
});

test('原生大纲、题卡、精读和练习在桌面与手机中联动（接口契约）',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'原生联动验收',course_name:'统计学',scenario:'chapter'});
  const material=await api('/learning-projects/'+p.id+'/materials','POST',{title:'抽样讲义',text:'总体与样本是统计推断的基础。'});
  let state={state:'question',reading:false,intake:false,mode:'study',request_id:'card-1',messages:[{role:'assistant',content:'请区分总体与样本。'}],
    workflow:{steps:['准备资料','学习大纲','讲解与理解检查','小结与复习'],step:2,confirm_outline:false,
      actions:[{id:'chapter_next',label:'继续下一节'}],practice_done:false,mock_done:false,mock_ready:false},
    question:{question_id:'card-1',prompt:'理解检查',options:[],questions:[{question_id:'child-1',prompt:'什么是总体？',options:[]}]},
    curriculum:{path_revision:2,map:{counts:{mastered:1,total:60},modules:Array.from({length:12},(_,i)=>({id:'m'+i,name:'知识模块 '+i,
      knowledge_points:[{id:'p'+i,name:'总体与样本 '+i,status:'learning',mastery:0,mastery_source:'evidence'}]}))},next:{reason:'继续理解总体'},reviews:[]}};
  const commands:Record<string,unknown>[]=[];
  await page.route(`**/api/v2/learning-projects/${p.id}/learning`,async route=>{
    if(route.request().method()==='POST'){
      const body=route.request().postDataJSON();commands.push(body);
      if(body.operation==='message'){
        state={...state,messages:[...state.messages,{role:'assistant',content:'可以从研究对象的范围来区分。'}]};
      }else{
        state={...state,state:'idle',question:null as never,reading:body.operation==='read'};
      }
      await route.fulfill({json:{data:{run_id:'contract-run'}}});
    }else await route.fulfill({json:{data:state}});
  });
  await page.route(`**/api/v2/learning-projects/${p.id}/concentrated-practice`,route=>route.fulfill({json:{data:{ready:true,options:[]}}}));
  await page.goto('/learning/projects/'+p.id);
  const outline=page.getByRole('button',{name:'学习大纲',exact:true});
  const drawer=page.getByRole('dialog',{name:'学习大纲'});
  const reply=page.getByRole('region',{name:'学习助教对话'});
  await expect(outline).toHaveAttribute('aria-expanded','false');
  await expect(reply).toContainText('请区分总体与样本。');
  await outline.click();
  await expect(drawer.getByText('已掌握 1 / 60 个知识点')).toBeVisible();
  await drawer.getByText('知识模块 0',{exact:true}).click();
  await expect(drawer.getByText('总体与样本 0',{exact:true})).toBeVisible();
  await drawer.getByRole('button',{name:'关闭学习大纲',exact:true}).click({timeout:10000});
  await expect(drawer).toBeHidden();
  const answer=page.locator('.native-question').getByRole('textbox');
  await answer.fill('总体是研究对象的全体');
  await page.getByLabel('向助教提问').fill('怎样区分总体与样本？');
  await page.getByRole('button',{name:'发送提问'}).click();
  await expect(reply).toContainText('可以从研究对象的范围来区分。');
  expect(commands.shift()).toEqual({operation:'message',text:'怎样区分总体与样本？'});
  await expect(answer).toHaveValue('总体是研究对象的全体');
  await page.getByRole('button',{name:'提交回答',exact:true}).click();
  await expect.poll(()=>commands.length).toBe(1);
  expect(commands[0]).toMatchObject({operation:'answer',expected_id:'card-1',answers:{'child-1':'总体是研究对象的全体'}});
  await page.getByRole('button',{name:'继续下一节',exact:true}).click();
  await expect.poll(()=>commands.length).toBe(2);
  expect(commands[1]).toEqual({operation:'guided',action_id:'chapter_next'});
  for(const viewport of [{width:1280,height:800},{width:390,height:844}]){
    await page.setViewportSize(viewport);
    const workspace=await page.getByRole('region',{name:'项目引导学习'}).boundingBox();
    const conversation=await reply.boundingBox();
    const content=await page.getByRole('region',{name:'项目学习内容'}).boundingBox();
    expect(Math.abs(workspace!.x+(workspace!.width-content!.width)/2-content!.x)).toBeLessThan(2);
    expect(Math.abs(conversation!.x+(conversation!.width-workspace!.width)/2-workspace!.x)).toBeLessThan(2);
    await outline.click();
    await expect(drawer).toBeInViewport();
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    await page.getByRole('button',{name:'集中练习',exact:true}).click();
    await expect(page.getByRole('dialog')).toContainText('合计生成 1–10 道新题');
    await page.getByRole('button',{name:'Close',exact:true}).click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  }
  await page.setViewportSize({width:1280,height:800});
  await outline.click();
  await page.getByRole('combobox',{name:'选择精读资料'}).click();
  await page.getByTitle('抽样讲义',{exact:true}).click();
  await page.getByRole('button',{name:'打开精读',exact:true}).click();
  await expect.poll(()=>commands.length).toBe(3);
  expect(commands[2]).toMatchObject({operation:'read',material_id:material.id});
  await expect(drawer).toBeHidden();
  await expect(page.getByRole('heading',{name:'资料精读',exact:true})).toBeVisible();
  await page.screenshot({path:'../.runtime/native-learning-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('.sidebar')).not.toBeInViewport();
  await page.screenshot({path:'../.runtime/native-learning-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
});

test('集中练习生成不限时题组，已交卷记录进入报告和自主错题（接口契约）',async({page})=>{
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'集中练习验收',course_name:'统计学',scenario:'chapter'});
  const base=`**/api/v2/learning-projects/${p.id}`;
  await page.route(base+'/learning',route=>route.fulfill({json:{data:{
    state:'idle',messages:[],writable:true,
    preparation:{ready:true,checks:[]},
  }}}));
  let generated:unknown;
  await page.route(base+'/concentrated-practice',route=>{
    if(route.request().method()==='POST'){
      generated=route.request().postDataJSON();
      return route.fulfill({json:{data:{run_id:'generated'}}});
    }
    return route.fulfill({json:{data:{ready:true,options:[{id:'sample',label:'抽样章节'}]}}});
  });
  await page.route(base+'/personal-runs/generated',route=>route.fulfill({json:{data:{
    id:'generated',state:'succeeded',result:{assessment_id:'untimed'},error:'',
  }}}));
  let drafts:Record<string,unknown>={};
  let submitted=false;
  await page.route('**/api/v2/assessments/untimed',route=>route.fulfill({json:{data:{
    id:'untimed',project_id:p.id,title:'集中练习 · 抽样章节',mode:'practice',
    state:submitted?'submitted':'active',deadline_at:null,server_now:new Date().toISOString(),revision:1,drafts,
    entries:[{task_id:'single',question:{id:'q',kind:'single',origin:'personal_practice',prompt:'哪项是总体？',
      options:{A:'全体',B:'一部分'},...(submitted?{answer:['A'],explanation:'总体是全体。'}:{})},
      ...(submitted?{result:{correct:false,feedback:'请区分总体与样本'}}:{})}],
  }}}));
  await page.route('**/api/v2/assessments/untimed/draft',route=>{
    drafts=route.request().postDataJSON().answers;
    return route.fulfill({json:{data:{revision:2}}});
  });
  await page.route('**/api/v2/assessments/untimed/submit',route=>{
    submitted=true;
    return route.fulfill({json:{data:{id:'untimed',state:'submitted'}}});
  });
  await page.route(base+'/attempt-history?**',route=>route.fulfill({json:{data:{
    partial:false,total:submitted?1:0,items:submitted?[{id:'platform:test',created_at:new Date().toISOString(),
      source:'concentrated',state:'incorrect',kind:'single',prompt:'哪项是总体？',options:{A:'全体',B:'一部分'},
      answer:'B',reference:'A',explanation:'总体是全体。',feedback:'请区分总体与样本',assessment_id:'untimed'}]:[],
  }}}));
  await page.goto('/learning/projects/'+p.id);
  await page.getByRole('button',{name:'集中练习',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'生成集中练习'});
  await dialog.getByLabel('单选题').fill('1');
  await dialog.getByRole('button',{name:'生成练习',exact:true}).click();
  await expect.poll(()=>generated).toMatchObject({single:1,multiple:0,essay:0});
  await dialog.getByRole('button',{name:'打开集中练习'}).click();
  await expect(page.getByText(/不限时练习/)).toBeVisible();
  await expect(page.getByText('参考答案：A')).toHaveCount(0);
  await page.getByRole('radio',{name:'B. 一部分'}).check();
  await expect.poll(()=>drafts.single).toBeTruthy();
  await page.reload();
  await expect(page.getByRole('radio',{name:'B. 一部分'})).toBeChecked();
  await page.getByRole('button',{name:'提交本次测评'}).click();
  await page.getByRole('dialog',{name:'确认整组交卷？'}).getByRole('button',{name:/确\s*定|OK/}).click();
  await expect(page.getByText('总体是全体。')).toBeVisible();
  await page.getByRole('link',{name:'学习报告',exact:true}).click();
  await page.getByText('哪项是总体？',{exact:true}).click();
  await expect(page.getByText('总体是全体。')).toBeVisible();
  await page.getByRole('link',{name:'错题诊断',exact:true}).click();
  await expect(page.getByRole('tab',{name:'自主学习'})).toHaveAttribute('aria-selected','true');
  await page.getByText('哪项是总体？',{exact:true}).click();
  await expect(page.getByRole('button',{name:'AI 诊断',exact:true})).toBeVisible();
  await expect(page.getByRole('tab',{name:'教师作业'})).toBeVisible();
});

test('复习待办留在项目，旧链接指向报告和项目（接口契约）',async({page})=>{
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'复习入口验收',course_name:'统计学',scenario:'chapter'});
  const base=`**/api/v2/learning-projects/${p.id}`;
  let selected='';
  let answered=false;
  await page.route(base+'/learning',route=>{
    if(route.request().method()==='POST'){
      const body=route.request().postDataJSON();
      if(body.operation==='answer')answered=true;
      else selected=body.review_objective;
      return route.fulfill({json:{data:{run_id:'review'}}});
    }
    return route.fulfill({json:{data:{
      state:selected&&!answered?'question':'idle',mode:selected?'review':'study',messages:[],writable:true,
      preparation:{ready:true,checks:[]},request_id:selected&&!answered?'card':'',
      question:selected&&!answered?{question_id:'card',prompt:'什么是总体？',options:[]}:null,
      due_reviews:[{id:'sample',name:'抽样',in_daily_plan:true,can_start:true},
        ...(!answered?[{id:'population',name:'总体',in_daily_plan:false,can_start:true}]:[])],
    }}});
  });
  await page.route(base+'/attempt-history?**',route=>route.fulfill({json:{data:{
    partial:false,total:answered?1:0,items:answered?[{id:'check:review',created_at:new Date().toISOString(),
      source:'review',state:'correct',kind:'short_answer',prompt:'什么是总体？',options:{},
      answer:'研究对象的全体',reference:'全体',explanation:'区分总体与样本。',feedback:'',assessment_id:null}]:[],
  }}}));
  await page.goto('/learning/library');
  await expect(page).toHaveURL(/\/learning\/projects$/);
  await expect(page.getByRole('link',{name:'资料与笔记',exact:true})).toHaveCount(0);
  await expect(page.getByRole('link',{name:'历史复习',exact:true})).toHaveCount(0);
  await page.goto('/learning/projects/'+p.id);
  await expect(page.getByRole('tab',{name:'课程与资料'})).toBeVisible();
  await expect(page.getByRole('tab',{name:'笔记与闪卡'})).toBeVisible();
  const due=page.getByRole('region',{name:'到期复习'});
  await expect(due.getByText('已安排在今日任务')).toBeVisible();
  await expect(due.getByRole('button',{name:'开始复习'})).toHaveCount(1);
  await due.getByRole('button',{name:'开始复习'}).click();
  await expect(due.getByText('复习已开始，请继续下方题卡。')).toBeVisible();
  expect(selected).toBe('population');
  await page.reload();
  await page.locator('.native-question').getByRole('textbox').fill('研究对象的全体');
  await page.getByRole('button',{name:'提交回答',exact:true}).click();
  await expect.poll(()=>answered).toBeTruthy();
  await page.goto('/reviews');
  await expect(page).toHaveURL(/\/learning\/reports\?source=review$/);
  await page.getByText('什么是总体？',{exact:true}).click();
  await expect(page.getByText('区分总体与样本。')).toBeVisible();
  await expect(page.getByRole('button',{name:'开始复习'})).toHaveCount(0);
});
