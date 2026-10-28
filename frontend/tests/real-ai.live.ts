import { test, expect, request, type APIRequestContext, type Page } from '@playwright/test';
import fs from 'node:fs';
type Run={id:string;purpose:string;state:string;error_code:string;model:string;metrics:Record<string,unknown>;result:{reliable:boolean;sources:{url:string;page:number;version_id:string}[];verification:{supported:boolean;conflict:boolean;leaks_answer:boolean}}};
let teacher:APIRequestContext,student:APIRequestContext;
const tokens=new Map<APIRequestContext,string>();
let tasks:{id:string;kind:string}[]=[];
const records:Run[]=[];
async function data(client:APIRequestContext,path:string,method='GET',body?:unknown){const r=await client.fetch('http://127.0.0.1:8001/api/v1'+path,{method,data:body,headers:{'X-CSRF-Token':tokens.get(client)??'','Idempotency-Key':crypto.randomUUID()}});expect(r.ok(),await r.text()).toBeTruthy();return (await r.json()).data;}
async function login(page:Page,user:string){await page.goto('/');await page.getByLabel('账号',{exact:true}).fill(user);await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');await page.getByRole('button',{name:'进入工作台'}).click();await expect(page.getByRole('button',{name:'退出登录'})).toBeVisible();}
async function runFromButton(page:Page,client:APIRequestContext,label:string){
  const response=page.waitForResponse(r=>r.url().endsWith('/api/v1/ai/requests')&&r.request().method()==='POST');
  await page.getByRole('button',{name:label,exact:true}).click();const created=await response;expect(created.ok(),await created.text()).toBeTruthy();const id=(await created.json()).data.id;
  let run:Run|undefined;
  await expect.poll(async()=>{run=(await data(client,'/ai/requests')).find((r:Run)=>r.id===id);return run?.state},{timeout:150000,intervals:[1000,2000,4000]}).toBe('succeeded');
  expect(run!.result.reliable,JSON.stringify(run)).toBeTruthy();expect(run!.result.verification.supported).toBeTruthy();expect(run!.result.verification.conflict).toBeFalsy();expect(run!.result.verification.leaks_answer).toBeFalsy();expect(run!.result.sources.length).toBeGreaterThan(0);records.push(run!);return run!;
}
test.describe.serial('真实 DeepSeek 页面验收，必须填写 Key 后单独运行',()=>{
  test.beforeAll(async()=>{
    teacher=await request.newContext();student=await request.newContext();
    for(const [c,name] of [[teacher,'teacher'],[student,'student']] as const){await data(c,'/auth/login','POST',{username:name,password:'Zhixing2026!'});tokens.set(c,(await data(c,'/me')).csrf_token);}
    const sources=(await data(teacher,'/content/sources')).items;
    const answers=new Map<string,string[]>();
    for(const s of sources){await expect.poll(async()=>(await data(teacher,'/content/indexes/'+s.id)).state,{timeout:90000}).toBe('ready');const detail=await data(teacher,'/sources/versions/'+s.id);for(const q of detail.questions)answers.set(q.id,q.answer);await data(teacher,'/documents/'+s.id+'/confirm','POST');await data(teacher,'/content/sources/'+s.id+'/submit','POST',{note:'独立真实AI验收：核对原创样例原页'});await data(teacher,'/content/sources/'+s.id+'/publish','POST',{note:'仅隔离验收环境发布'});}
    const subject=(await data(student,'/catalog')).subjects[0].id;
    await data(student,'/goals/current','PUT',{subject_id:subject,exam_year:2027,target_score:75,daily_minutes:60});await data(student,'/diagnostics','POST',{subject_id:subject});const diag=await data(student,'/diagnostics/current');
    for(const task of diag.tasks){const a=await data(student,'/tasks/'+task.id+'/attempts','POST');await data(student,'/attempts/'+a.id+'/draft','PATCH',{answer:answers.get(a.question.id),response_text:'',process:'独立验收诊断：核对材料条件',duration_seconds:30,revision:a.revision});await data(student,'/attempts/'+a.id+'/submit','POST');}
    await data(student,'/diagnostics/'+diag.id+'/submit','POST');tasks=(await data(student,'/plans/today')).all_tasks;
  });
  test.afterAll(async()=>{fs.mkdirSync('../.runtime',{recursive:true});fs.writeFileSync('../.runtime/real-ai-acceptance.json',JSON.stringify({date:new Date().toISOString(),provider:'DeepSeek',runs:records,automatedChecksOnly:true,humanQualityReview:'required'},null,2));await teacher?.dispose();await student?.dispose();});
  for(const [purpose,label] of [['question','带依据答疑'],['hint','获取 AI 提示'],['cause','分析候选错因'],['evaluation','分维度辅助评价']] as const){
    for(let i=0;i<2;i++)test(`${purpose} 真实样例 ${i+1}`,async({page})=>{
      const t=tasks.filter(t=>purpose==='evaluation'?t.kind==='essay':t.kind!=='essay')[i];let a=await data(student,'/tasks/'+t.id+'/attempts','POST');
      if(['cause','evaluation'].includes(purpose)&&a.status==='draft'){await data(student,'/attempts/'+a.id+'/draft','PATCH',{answer:purpose==='evaluation'?[]:['A'],response_text:purpose==='evaluation'?'应核对材料中的事实与条件，将原理与具体行为联系，避免以单个案例推断普遍结论。':'',process:'我对原理适用条件和材料主体的区分还不清楚。',duration_seconds:40,revision:a.revision});a=await data(student,'/attempts/'+a.id+'/submit','POST');}
      await login(page,'student');await page.goto('/study/'+t.id);await page.getByRole('textbox',{name:'当前题目疑问'}).fill('请解释资料的概念与适用条件，遵循当前提示级别。');if(purpose==='hint'){for(const level of [1,2,3,4]){await page.getByLabel('AI提示级别').click();await page.getByText(`第 ${level} 级`,{exact:true}).last().click();await runFromButton(page,student,label)}}else await runFromButton(page,student,label);await page.screenshot({path:`../.runtime/real-${purpose}-${i}.png`,fullPage:true});
    });
  }
  for(let i=0;i<2;i++)test(`教案真实样例 ${i+1}`,async({page})=>{await login(page,'teacher');await page.getByRole('link',{name:'AI 备课',exact:true}).click();const catalog=await data(teacher,'/catalog');await page.getByLabel('备课知识点').click();await page.getByText(catalog.knowledge[i].name,{exact:true}).last().click();await runFromButton(page,teacher,'生成教案草稿');await expect(page.getByRole('textbox',{name:'教案正文'}).first()).toBeVisible();});
  for(let i=0;i<2;i++)test(`引用核验与真实原页 ${i+1}`,async({page})=>{const r=records.filter(r=>r.result.sources?.length)[i];expect(r).toBeTruthy();const source=r.result.sources[0];expect(source.page).toBeGreaterThan(0);await login(page,'student');await page.goto(source.url);await expect(page.getByRole('img',{name:`原文第 ${source.page} 页`})).toBeVisible();});
});
