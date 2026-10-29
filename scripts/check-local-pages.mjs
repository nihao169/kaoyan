// Read-only page smoke check against the delivered local service. No submissions.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
const {chromium}=require('@playwright/test');
const browser=await chromium.launch({channel:'msedge',headless:true});
const checks=[];
try{
  for(const [user,paths] of [['teacher',['/assignments','/teacher','/content']],['student',['/','/mistakes','/history','/reviews']],['admin',['/users','/ai-settings']]]){
    const context=await browser.newContext({baseURL:'http://127.0.0.1:5173'});
    const page=await context.newPage();const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('/');await page.getByLabel('账号',{exact:true}).fill(' '+user+' ');
    await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
    await page.getByRole('button',{name:'进入工作台',exact:true}).click();
    await page.getByRole('button',{name:'退出登录',exact:true}).waitFor();
    for(const path of paths){
      await page.goto(path);await page.getByRole('button',{name:'退出登录',exact:true}).waitFor();
      await page.waitForLoadState('networkidle');
      if(await page.getByText('Failed to execute',{exact:false}).count())throw new Error('Raw response failure: '+path);
      if(await page.getByRole('button',{name:'重试',exact:true}).count())throw new Error('Failed page: '+path);
      if(errors.length)throw new Error(JSON.stringify(errors));
      checks.push({user,path,loaded:true});
    }
    await page.screenshot({path:fileURLToPath(new URL('../.runtime/delivered-'+user+'.png',import.meta.url)),fullPage:true});
    await context.close();
  }
  fs.writeFileSync(new URL('../.runtime/delivered-page-checks.json',import.meta.url),JSON.stringify(checks,null,2));
  console.log(JSON.stringify(checks));
}finally{await browser.close();}
