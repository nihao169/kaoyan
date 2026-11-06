import {test,expect,type Page} from '@playwright/test';
import fs from 'node:fs';
const live=process.env.ZX_REAL_AI==='1';
const native=process.env.ZX_NATIVE_TEACHING_E2E==='1';
const report:{provider:string;checks:string[];runs:unknown[];humanReview:string}={provider:native?'DeepTutor native':live?'DeepSeek real':'explicit controlled browser provider',checks:[],runs:[],humanReview:'required for real teaching quality'};
async function login(page:Page,user:string){await page.goto('/');await page.getByLabel('账号',{exact:true}).fill(user);await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');await page.getByRole('button',{name:'进入工作台'}).click();await expect(page.getByRole('button',{name:'退出登录'})).toBeVisible();}
async function data(page:Page,path:string,method='GET',body?:unknown){const me=await page.request.get('/api/v1/me');const token=(await me.json()).data.csrf_token;const r=await page.request.fetch('/api/v1'+path,{method,data:body,headers:{'X-CSRF-Token':token,'Idempotency-Key':crypto.randomUUID()}});expect(r.ok(),await r.text()).toBeTruthy();return (await r.json()).data;}

async function finished(page:Page,id:string,timeout:number){
  let result:any;
  try{
    await expect.poll(async()=>{result=await data(page,'/agent-runs/'+id);return ['succeeded','failed','cancelled'].includes(result.state)},{timeout,intervals:[1000,2000,4000]}).toBe(true);
  }finally{if(result)report.runs.push(result)}
  expect(result.state,`${result.stage} ${result.error_code||''}`).toBe('succeeded');
  return result;
}

test.afterAll(()=>{fs.mkdirSync('../.runtime',{recursive:true});fs.writeFileSync(`../.runtime/${live?'real':'controlled'}-teaching-acceptance.json`,JSON.stringify(report,null,2));});

test('上传原文、Agent出题、教师作业、整组提交、手动错题诊断与针对性练习',async({browser})=>{
  const teacherContext=await browser.newContext();const studentContext=await browser.newContext();
  const teacher=await teacherContext.newPage();const student=await studentContext.newPage();
  const errors:string[]=[];teacher.on('pageerror',e=>errors.push(e.message));student.on('pageerror',e=>errors.push(e.message));
  try{
    await login(teacher,'teacher');await teacher.getByRole('link',{name:'教学内容',exact:true}).click();
    await teacher.getByRole('button',{name:'导入新资料',exact:true}).click();await teacher.getByText('上传文件',{exact:true}).click();
    await teacher.locator('#source-file').setInputFiles('../测试导入资料/政治模拟讲义_实践认识与辩证方法.md');
    await teacher.getByRole('button',{name:'上传并解析',exact:true}).click();await expect(teacher.getByRole('heading',{name:'原文与 Agent 出题',exact:true})).toBeVisible();
    await expect(teacher.getByRole('button',{name:'启用并生成',exact:true})).toBeEnabled({timeout:60000});
    await teacher.getByRole('spinbutton',{name:'单选题',exact:true}).fill('1');await teacher.getByRole('spinbutton',{name:'多选题',exact:true}).fill('1');await teacher.getByRole('spinbutton',{name:'分析题',exact:true}).fill('1');
    const enabled=teacher.waitForResponse(r=>r.url().endsWith('/enable')&&r.request().method()==='POST');await teacher.getByRole('button',{name:'启用并生成',exact:true}).click();const enabledResponse=await enabled;expect(enabledResponse.ok(),await enabledResponse.text()).toBeTruthy();const generation=(await enabledResponse.json()).data;
    const generated=await finished(teacher,generation.id,native?540000:live?240000:60000);expect(generated.output.question_ids).toHaveLength(3);
    const bank=await data(teacher,'/teaching/questions');expect(bank).toHaveLength(3);expect(bank.every((q:any)=>q.sources.length>0)).toBeTruthy();
    report.checks.push('real file upload; one enable action; generated questions with real citations');
    await teacher.getByRole('link',{name:'作业与批阅',exact:true}).click();await expect(teacher.getByRole('heading',{name:'Agent 生成题库',exact:true})).toBeVisible();
    await teacher.locator('.ant-table-thead input[type=checkbox]').check();await teacher.getByRole('button',{name:'布置所选题目（3）',exact:true}).click();
    const title='Agent作业验收';await teacher.getByLabel('作业名称',{exact:true}).fill(title);await teacher.getByLabel('班级',{exact:true}).click();await teacher.getByTitle('政治基础研习班',{exact:true}).last().click();
    const published=teacher.waitForResponse(r=>r.url().endsWith('/teacher/assignments')&&r.request().method()==='POST');await teacher.getByRole('button',{name:'发布作业',exact:true}).click();const assignment=(await (await published).json()).data;
    await login(student,'student');await student.getByRole('link',{name:'教师作业',exact:true}).click();await expect(student.getByRole('heading',{name:title,exact:true})).toBeVisible();
    const started=student.waitForResponse(r=>r.url().endsWith('/assignments/'+assignment.id+'/start')&&r.request().method()==='POST');
    await student.getByRole('button',{name:'开始作业',exact:true}).click();
    const group=await data(student,'/assignments/'+assignment.id+'/start','POST');
    const firstStart=await started;expect(firstStart.ok(),await firstStart.text()).toBeTruthy();
    expect((await firstStart.json()).data.id).toBe(group.id);
    for(let i=0;i<group.entries.length;i++){
      await student.getByRole('button',{name:`切换第${i+1}题`,exact:true}).click();const entry=group.entries[i];const q=entry.attempt.question;
      await expect(student.getByRole('heading',{name:q.prompt,exact:true})).toBeVisible();
      if(q.kind==='essay')await student.getByRole('textbox',{name:'你的材料分析',exact:true}).fill('实践是认识的来源，材料中的调查和反馈能够修正原有判断。还需要核对具体条件，再将认识用于实践。');
      else {const original=bank.find((b:any)=>b.id===q.id);const incomplete=Object.keys(q.options).find(k=>!original.answer.includes(k))??original.answer[0];await student.getByRole(q.kind==='single'?'radio':'checkbox').nth(Object.keys(q.options).indexOf(incomplete)).check();}
      await student.getByRole('textbox',{name:'思考过程',exact:true}).fill('我没有把材料条件与原理区分清楚，需要进一步核对。');
      await student.getByRole('button',{name:'保存草稿',exact:true}).click();await expect(student.getByText('已保存到服务器',{exact:true})).toBeVisible();
    }
    await student.reload();await expect(student.getByRole('textbox',{name:'思考过程',exact:true})).toHaveValue('我没有把材料条件与原理区分清楚，需要进一步核对。');
    await student.getByRole('button',{name:'提交整组作业',exact:true}).click();await expect(student.getByText('整组已提交',{exact:true})).toBeVisible();
    const essay=group.entries.find((e:any)=>e.attempt.question.kind==='essay').attempt;
    let preliminary:any;await expect.poll(async()=>{preliminary=await data(student,'/attempts/'+essay.id);return preliminary.grading_state},{timeout:native?360000:live?180000:45000,intervals:[1000,2000]}).toBe('AI初评待教师确认');expect(preliminary.evaluation).toBeNull();
    await teacher.goto('/teacher/attempts/'+essay.id);await expect(teacher.getByRole('button',{name:'确认AI初评',exact:true})).toBeVisible();await teacher.getByRole('button',{name:'确认AI初评',exact:true}).click();await expect(teacher.getByText('教师已确认',{exact:true})).toBeVisible();report.checks.push('whole-group save/submit; AI suggestion separate; teacher confirmation');
    await student.getByRole('link',{name:'错题诊断',exact:true}).click();const mistakes=await data(student,'/mistake-diagnoses');const multiple=mistakes.find((m:any)=>m.kind==='multiple');expect(multiple.diagnosis).toBeNull();expect(multiple.practices).toHaveLength(0);
    await student.goto('/mistakes?attempt='+multiple.attempt_id);await expect(student.getByText('你的选择',{exact:true})).toBeVisible();await expect(student.getByText('漏选',{exact:true}).first()).toBeVisible();
    const requested=student.waitForResponse(r=>r.url().endsWith('/diagnose')&&r.request().method()==='POST');await student.getByRole('button',{name:'AI诊断',exact:true}).click();const diagnosis=(await (await requested).json()).data;
    await finished(student,diagnosis.id,native?360000:live?180000:45000);await expect(student.getByRole('heading',{name:'学习建议',exact:true})).toBeVisible();
    expect((await data(student,'/mistake-diagnoses')).find((m:any)=>m.id===multiple.id).practices).toHaveLength(0);
    const next=student.waitForResponse(r=>r.url().endsWith('/practice-generations')&&r.request().method()==='POST');await student.getByRole('button',{name:'生成针对性练习',exact:true}).click();const target=(await (await next).json()).data;
    const personal=await finished(student,target.id,native?540000:live?240000:45000);expect(personal.output.question_ids).toHaveLength(3);expect((await data(teacher,'/teaching/questions')).length).toBe(3);
    await student.getByRole('button',{name:'开始针对性练习',exact:true}).click();await expect(student.getByRole('button',{name:'提交整组练习',exact:true})).toBeVisible();
    const exercises=await data(student,'/practice-groups/'+personal.output.practice_id+'/open','POST');
    for(let i=0;i<exercises.entries.length;i++){
      const entry=exercises.entries[i];
      await student.getByRole('button',{name:`切换第${i+1}题`,exact:true}).click();
      await expect(student.getByText(entry.attempt.question.prompt,{exact:true}).first()).toBeVisible();
      // Teacher view supplies the answer key for this automated regression only.
      // The student progress/attempt APIs must not expose it before submission.
      expect(entry.attempt.question.answer==null).toBeTruthy();
      expect(personal.output.questions).toBeUndefined();
      const marking=await data(teacher,'/teacher/attempts/'+entry.attempt.id);
      for(const answer of marking.question.answer){await student.getByRole('checkbox').nth(Object.keys(entry.attempt.question.options).indexOf(answer)).check();}
      await student.getByRole('textbox',{name:'思考过程',exact:true}).fill('重新核对原文条件与全部选项后作答。');
      await student.getByRole('button',{name:'保存草稿',exact:true}).click();
      await expect.poll(async()=>{const saved=await data(student,'/attempts/'+entry.attempt.id);return [...saved.answer].sort()}).toEqual([...marking.question.answer].sort());
    }
    const submitted=student.waitForResponse(r=>r.url().endsWith('/practice-groups/'+personal.output.practice_id+'/submit')&&r.request().method()==='POST');
    await student.getByRole('button',{name:'提交整组练习',exact:true}).click();
    const submissionResponse=await submitted;expect(submissionResponse.ok(),await submissionResponse.text()).toBeTruthy();
    await expect(student.getByText('整组已提交',{exact:true})).toBeVisible();
    const result=(await data(student,'/mistake-diagnoses')).find((m:any)=>m.id===multiple.id);
    expect(result.resolved).toBeTruthy();expect(result.practice_results[0].independent_correct).toBe(3);
    report.checks.push('personal practice submitted; independent correct evidence and review schedules');
    // Verify all delivery stages are real in live mode, with no controlled provider allowed.
    if(live)expect(report.runs.every((r:any)=>r.model!=='controlled-browser-provider')).toBeTruthy();
    if(native)expect(report.runs.every((r:any)=>r.model.startsWith('deeptutor:')&&r.metrics.provider==='DeepTutor')).toBeTruthy();
    await student.screenshot({path:`../.runtime/${live?'real':'controlled'}-targeted-practice.png`,fullPage:true});
    await student.setViewportSize({width:390,height:844});await expect(student.getByText('整组已提交',{exact:true})).toBeVisible();expect(await student.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy();
    report.checks.push('manual diagnosis and new practice; private question bank; mobile layout');expect(errors).toEqual([]);
  }finally{await teacherContext.close();await studentContext.close();}
});
