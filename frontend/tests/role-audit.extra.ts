import {test,expect,type Page} from '@playwright/test';
async function login(page:Page,name:string){
 await page.goto('/');await page.getByLabel('账号',{exact:true}).fill(name);
 await page.getByLabel('密码',{exact:true}).fill('Zhixing2026!');
 await page.getByRole('button',{name:'进入工作台'}).click();
 await expect(page.getByRole('button',{name:'退出登录'})).toBeVisible();
}
test('管理员创建学生账号，新学生登录且不能上传资料',async({page})=>{
 await login(page,'admin');await page.getByRole('link',{name:'账号管理',exact:true}).click();
 await page.getByRole('button',{name:'创建账号',exact:true}).click();
 const d=page.getByRole('dialog');
 await d.getByLabel('姓名',{exact:true}).fill('实际验证学生');
 await d.getByLabel('登录账号',{exact:true}).fill('audit_student');
 await d.getByLabel('初始密码',{exact:true}).fill('Zhixing2026!');
 await d.getByLabel('角色',{exact:true}).click();
 await page.getByRole('option',{name:'学生',exact:true}).click();
 await d.getByLabel('角色',{exact:true}).press('Escape');
 await d.getByLabel('所属班级',{exact:true}).click();
 await page.getByRole('option',{name:'政治基础研习班',exact:true}).click();
 await d.getByRole('button',{name:'创建账号',exact:true}).click();
 await expect(page.getByRole('cell',{name:'audit_student',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'退出登录'}).click();await login(page,'audit_student');
 await expect(page.getByRole('heading',{name:'实际验证学生，今天也向前一步',exact:true})).toBeVisible();
 await expect(page.locator('nav').getByText('教学内容',{exact:true})).toHaveCount(0);
 await page.goto('/content');
 await expect(page.getByText('需要教师或机构管理员角色才能管理教学内容。',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'导入新资料',exact:true})).toHaveCount(0);
});
test('教师通过页面上传 TXT 并读取真实正文',async({page})=>{
 await login(page,'teacher');await page.getByRole('link',{name:'教学内容',exact:true}).click();
 await page.getByRole('button',{name:'导入新资料',exact:true}).click();
 const d=page.getByRole('dialog');await d.getByRole('radio',{name:'上传文件',exact:true}).check();
 await d.locator('input[type=file]').setInputFiles({name:'功能实测资料.txt',mimeType:'text/plain',buffer:Buffer.from('# 上传验证\n\n这是通过教师页面上传的原始文本，用于核对资料导入是否真实落库。','utf8')});
 await d.getByLabel('对应知识点',{exact:true}).click();await page.getByRole('option',{name:'实践与认识',exact:true}).click();
 await d.getByRole('button',{name:'保存为草稿',exact:true}).click();
 await expect(page.getByRole('heading',{name:'功能实测资料.txt',exact:true})).toBeVisible();
 await expect(page.getByRole('textbox',{name:'资料原文正文',exact:true})).toHaveValue(/通过教师页面上传/);
 await expect(page.getByRole('button',{name:'提交审核',exact:true})).toBeVisible();
});
