import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
async function login(page:Page,user:string){
  await page.goto('/');await page.getByLabel('账号',{exact:true}).fill(user);await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');await page.getByRole('button',{name:'进入工作台'}).click();await expect(page.getByRole('button',{name:'退出登录'})).toBeVisible();
}
test('管理员查看未配置状态，真实连接不能伪造成功',async({page})=>{
  await login(page,'admin');await page.getByRole('link',{name:'AI 服务状态',exact:true}).click();await expect(page.getByText('未配置',{exact:true})).toBeVisible();await page.getByRole('button',{name:'测试真实连接'}).click();await expect(page.getByText('请在服务端 .env 填写 MODEL_API_KEY 后重启服务')).toBeVisible();
});
for(const extension of ['pdf','docx']){
test(`教师真实导入 ${extension} 并核对原页`,async({page})=>{
  await login(page,'teacher');await page.getByRole('link',{name:'教学内容',exact:true}).click();await page.getByRole('button',{name:'导入新资料'}).click();await page.getByText('上传文件',{exact:true}).click();await page.locator('#source-file').setInputFiles(path.resolve('..','docs','samples','politics-01-v1.'+extension));
  await page.getByLabel('对应知识点',{exact:true}).click();await page.getByText('实践与认识',{exact:true}).last().click();await page.getByRole('button',{name:'保存为草稿'}).click();await expect(page.getByRole('heading',{name:'原页与解析对照'})).toBeVisible();await expect(page.getByRole('img',{name:'原文第 1 页'})).toBeVisible({timeout:90000});
  await expect.poll(()=>page.getByRole('img',{name:'原文第 1 页'}).evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBeGreaterThan(0);await page.getByRole('button',{name:'确认原页与提取文本一致'}).click();await expect(page.getByRole('button',{name:'已确认原页核对'})).toBeDisabled();
  await page.screenshot({path:`../.runtime/browser-${extension}-preview.png`,fullPage:true});
});}
test('学生查看待诊断状态，教师打开转办和备课页面',async({page})=>{
  await login(page,'student');await page.getByRole('link',{name:'知识点诊断',exact:true}).click();await expect(page.getByRole('heading',{name:'知识点诊断',exact:true})).toBeVisible();await expect(page.getByText('待诊断',{exact:true}).first()).toBeVisible();await page.getByRole('button',{name:'退出登录'}).click();await login(page,'teacher');await page.getByRole('link',{name:'AI 备课',exact:true}).click();await expect(page.getByRole('button',{name:'生成教案草稿'})).toBeDisabled();await page.getByRole('link',{name:'学习困难转办',exact:true}).click();await expect(page.getByRole('heading',{name:'学习困难转办',exact:true})).toBeVisible();
});
