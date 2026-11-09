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
    await page.getByRole('button',{name:'创建并与助教开始学习'}).click();
    await expect(page.getByRole('tab',{name:'与助教学习',exact:true})).toHaveAttribute('aria-selected','true');
    await expect(page.getByRole('heading',{name:'与助教一起学习'})).toBeVisible();
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
  await expect(page.getByRole('heading',{name:'与助教一起学习'})).toBeVisible();
  expect((await api('/learning-projects/'+p.id)).scenario).toBe('final');
});

test('原生大纲、题卡、精读和练习在桌面与手机中联动（接口契约）',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const api=await login(page);
  const p=await api('/learning-projects','POST',{title:'原生联动验收',course_name:'统计学',scenario:'chapter'});
  const material=await api('/learning-projects/'+p.id+'/materials','POST',{title:'抽样讲义',text:'总体与样本是统计推断的基础。'});
  let state={state:'question',reading:false,intake:false,mode:'study',request_id:'card-1',messages:[{role:'assistant',content:'请区分总体与样本。'}],
    question:{question_id:'card-1',prompt:'理解检查',options:[],questions:[{question_id:'child-1',prompt:'什么是总体？',options:[]}]},
    curriculum:{path_revision:2,map:{counts:{mastered:1,total:60},modules:Array.from({length:12},(_,i)=>({id:'m'+i,name:'知识模块 '+i,
      knowledge_points:[{id:'p'+i,name:'总体与样本 '+i,status:'learning',mastery:0,mastery_source:'evidence'}]}))},next:{reason:'继续理解总体'},reviews:[]}};
  const commands:Record<string,unknown>[]=[];
  await page.route(`**/api/v2/learning-projects/${p.id}/learning`,async route=>{
    if(route.request().method()==='POST'){
      const body=route.request().postDataJSON();commands.push(body);
      state={...state,state:'idle',question:null as never,reading:body.operation==='read'};
      await route.fulfill({json:{data:{run_id:'contract-run'}}});
    }else await route.fulfill({json:{data:state}});
  });
  await page.route(`**/api/v2/learning-projects/${p.id}/learning/practice`,route=>route.fulfill({json:{data:{items:[]}}}));
  await page.goto('/learning/projects/'+p.id);
  await expect(page.getByText('已掌握 1 / 60 个知识点')).toBeVisible();
  await page.getByRole('textbox').fill('总体是研究对象的全体');
  await page.getByRole('button',{name:'提交回答',exact:true}).click();
  await expect.poll(()=>commands.length).toBe(1);
  expect(commands[0]).toMatchObject({operation:'answer',expected_id:'card-1',answers:{'child-1':'总体是研究对象的全体'}});
  for(const viewport of [{width:1280,height:800},{width:390,height:844}]){
    await page.setViewportSize(viewport);
    await page.getByRole('button',{name:'集中练习',exact:true}).click();
    await expect(page.getByRole('dialog')).toContainText('当前路径还没有已保存的题目');
    await page.getByRole('button',{name:'Close',exact:true}).click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  }
  await page.setViewportSize({width:1280,height:800});
  await page.getByRole('combobox',{name:'选择精读资料'}).click();
  await page.getByTitle('抽样讲义',{exact:true}).click();
  await page.getByRole('button',{name:'打开精读',exact:true}).click();
  await expect.poll(()=>commands.length).toBe(2);
  expect(commands[1]).toMatchObject({operation:'read',material_id:material.id});
  await expect(page.getByRole('heading',{name:'资料精读',exact:true})).toBeVisible();
  await page.screenshot({path:'../.runtime/native-learning-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('.sidebar')).not.toBeInViewport();
  await page.screenshot({path:'../.runtime/native-learning-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
});
