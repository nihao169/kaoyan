import { TeacherLearningChain } from './extensions';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Collapse, Form, Input, InputNumber, Modal, Select, Space, Statistic, Table, Tag } from 'antd';
import { CheckSquareOutlined, FileTextOutlined, PlusOutlined, TeamOutlined } from '@ant-design/icons';
import { api, key, kindName, type Attempt, type Contracts, type Evaluation } from './api';
import { Blank, PageTitle, Sources, State, Status, date, useRun } from './ui';

type Student = Contracts['TeacherOverviewOutput'];
type TeacherAttemptItem = Contracts['TeacherAttemptOutput'];
type Case = Contracts['ReviewCaseOutput'];

export function Teacher() {
  const [search]=useSearchParams();
  const assignment=search.get('assignment');
  const overview=useQuery({queryKey:['teacher-overview'],queryFn:()=>api<Student[]>('/teacher/overview')});
  const attempts=useQuery({queryKey:['teacher-attempts',assignment],queryFn:()=>api<TeacherAttemptItem[]>('/teacher/attempts'+(assignment?'?assignment_id='+assignment:'')),refetchInterval:q=>q.state.data?.some(a=>a.grading_state==='AI初评中')?3000:false});
  const [pendingOnly,setPendingOnly]=useState(false);
  const pending=attempts.data?.filter(a=>a.status==='pending_teacher').length??0;
  return <><PageTitle title={assignment?'作业作答与批阅':'教学概览'} description="系统判分、AI建议与教师确认分别记录，教师只确认分析题或处理异议。" action={<Link to="/assignments"><Button type="primary">布置作业与批阅</Button></Link>}/>
    <div className="stat-grid"><Card><Statistic title="授权班级学生" value={overview.data?.length??0} suffix="人" prefix={<TeamOutlined aria-hidden/>}/><p>仅展示你有权限查看的学生</p></Card><Card><Statistic title="已提交作答" value={attempts.data?.length??0} suffix="次" prefix={<FileTextOutlined aria-hidden/>}/><p>保留原始答案与思考过程</p></Card><Card><Statistic title="分析题待评" value={pending} suffix="份" prefix={<CheckSquareOutlined aria-hidden/>}/><p>人工评分后进入正式成绩</p></Card></div>
    <section className="panel"><div className="section-heading"><div><h2>班级学情</h2><p>得分为已评价作答累计，包含练习和复习，不是考试预测分数。</p></div></div><State query={overview}><Table rowKey="id" pagination={false} dataSource={overview.data??[]} scroll={{x:600}} columns={[
      {title:'学生',dataIndex:'name'},{title:'已提交作答',dataIndex:'attempts'},{title:'待评分析题',dataIndex:'pending',render:v=><Tag color={v?'gold':'default'}>{v} 份</Tag>},{title:'已评价累计得分',render:(_,s)=>`${s.score} / ${s.max_score}`},
    ]}/></State></section>
    <section className="panel section-space"><div className="section-heading"><div><h2>学生作答</h2><p>进入详情可查看思路、提示使用、内容版本和评分历史。</p></div><Button type={pendingOnly?'primary':'default'} onClick={()=>setPendingOnly(!pendingOnly)}>{pendingOnly?'显示全部':'只看待评'}</Button></div><State query={attempts}><Table rowKey="id" dataSource={(attempts.data??[]).filter(a=>!pendingOnly||a.status==='pending_teacher')} pagination={{pageSize:8}} scroll={{x:800}} columns={[
      {title:'学生',dataIndex:'student',width:100},{title:'题目',render:(_,a)=><Link to={'/teacher/attempts/'+a.id}>{a.prompt}</Link>},{title:'题型',dataIndex:'kind',render:kindName,width:90},{title:'评价状态',dataIndex:'grading_state',render:v=><Tag>{v}</Tag>,width:160},{title:'正式分',render:(_,a)=>a.evaluation?.score??'尚未确认',width:90},{title:'操作',render:(_,a)=><Link to={'/teacher/attempts/'+a.id}><Button type={a.status==='pending_teacher'?'primary':'default'}>{a.status==='pending_teacher'?'确认评分':'查看作答'}</Button></Link>,width:130},{title:'提交时间',dataIndex:'submitted_at',render:date,width:140},
    ]}/></State></section>
  </>;
}

export function TeacherAttempt() {
  const {attemptId}=useParams();
  const [search]=useSearchParams();
  const caseId=search.get('case');
  const navigate=useNavigate();
  const query=useQuery({queryKey:['teacher-attempt',attemptId],queryFn:()=>api<Attempt>('/teacher/attempts/'+attemptId),refetchInterval:q=>q.state.data?.grading_state==='AI初评中'?3000:false});
  const {busy,run}=useRun();
  const [form]=Form.useForm();
  const a=query.data;
  useEffect(()=>{if (a) form.setFieldsValue({parts:a.question.kind==='essay'?a.question.rubric?.map((_,i)=>a.evaluation?.parts[i]??a.ai_suggestion?.parts?.[i]??0):[a.evaluation?.score??0],feedback:a.evaluation?'':a.ai_suggestion?.feedback??''})},[a,form]);
  async function grade(values:{parts:number[];feedback:string}) {
    if(!a)return;
    const body={...values,expected_revision:a.evaluation?.revision??0};
    const result=await run(()=>api(caseId?'/review-cases/'+caseId+'/resolve':'/teacher/attempts/'+a.id+'/evaluations','POST',body,key()),caseId?'复核结果已保存':'正式评分已保存');
    if(result&&caseId) navigate('/cases');
  }
  return <><PageTitle title={caseId?'评价复核':'作答与评价详情'} description="原始作答保持不变；新的评分或复核会形成独立的评价修订。" action={<Link to={caseId?'/cases':'/teacher'}><Button>返回列表</Button></Link>}/><State query={query}>{a&&<>
    <TeacherLearningChain attemptId={a.id}/><div className="study-layout"><section className="panel question-panel"><div className="question-meta"><Tag color="green">{kindName(a.question.kind)}</Tag><Tag>{a.grading_state}</Tag><span>题目版本 {a.question.number}</span><span>使用 {a.hint_level} 级提示</span></div><h2 className="question-prompt">{a.question.prompt}</h2>
      {Object.entries(a.question.options).map(([k,v])=><p className="teacher-option" key={k}><strong>{k}</strong> {v}</p>)}
      <div className="analysis-box"><h3>学生原始答案</h3><p className="preserve-text">{a.question.kind==='essay'?a.response_text:a.answer.join('、')}</p><h3>原始思考过程</h3><p className="preserve-text">{a.process||'未填写思考过程'}</p><span className="muted">用时 {a.duration_seconds} 秒 · {a.hint_level?'辅助作答':'未使用提示'}</span></div>
      <div className="analysis-box"><h3>审核解析与评分依据</h3><p>{a.question.explanation}</p>{!!a.question.answer?.length&&<p>审核答案：{a.question.answer.join('、')}</p>}</div>
      {a.evaluation&&<Alert type="info" showIcon message={`当前有效评价：${a.evaluation.score} / ${a.question.max_score} 分 · 第 ${a.evaluation.revision} 次评价`} description={a.evaluation.feedback}/>}
    </section><aside className="panel"><h2>{caseId?'填写复核评价':a.evaluation?'修订教师评价':'分析题评分'}</h2>
      {a.ai_suggestion?.parts&&<><Alert type="info" message={`AI建议分：${a.ai_suggestion.score} / ${a.question.max_score}，${a.ai_suggestion.confirmed?'已确认':'尚未计入正式成绩'}`} description={a.ai_suggestion.feedback}/>{!a.evaluation&&!caseId&&<Button className="section-space" type="primary" block loading={busy} onClick={()=>run(()=>api('/teacher/attempts/'+a.id+'/confirm-ai-evaluation','POST',{},key()),'AI初评已由教师确认为正式成绩')}>确认AI初评</Button>}<Collapse className="section-space" items={[{key:'ai-sources',label:'核对AI初评依据',children:<Sources items={a.ai_suggestion.sources??[]}/>}]}/></>}
      {a.grading_state==='AI初评中'&&<p>Agent 正在按评分要点初评，稍后可确认；也可直接手工评分。</p>}
      {a.question.kind==='essay'||caseId?<Form form={form} layout="vertical" onFinish={grade} requiredMark={false}>
      {(a.question.kind==='essay'?a.question.rubric??[]:[{label:'复核得分',score:a.question.max_score}]).map((r,i)=><Form.Item key={i} name={['parts',i]} label={`${r.label}（满分 ${r.score}）`} rules={[{required:true,message:'请填写得分'}]}><InputNumber min={0} max={r.score} precision={0} style={{width:'100%'}}/></Form.Item>)}
      <Form.Item name="feedback" label={caseId?'复核说明与修改原因':'评语与依据'} rules={[{required:true,message:'请填写评价说明'}]}><Input.TextArea rows={5} maxLength={5000}/></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy} block>{caseId?'保存复核结果':'保存正式评分'}</Button><p className="small-note">分项总和自动计算；提交时核对当前评价版本，避免覆盖其他教师的修改。</p>
    </Form>:<p className="muted">客观题已按审核答案判分。如学生提出异议，请从评价复核入口处理。</p>}</aside></div>
    <section className="panel section-space"><h2>原文依据</h2><Sources items={a.sources??[]}/></section>
    <section className="panel section-space"><h2>评价历史</h2><Table rowKey="number" pagination={false} dataSource={a.revisions??[]} columns={[{title:'修订',dataIndex:'number'},{title:'得分',dataIndex:'score'},{title:'方式',dataIndex:'method',render:v=>v==='rule'?'规则判分':'教师评价'},{title:'说明',dataIndex:'feedback'}]}/><Collapse className="section-space" items={[{key:'events',label:'提示与学习事件',children:a.events?.length?<div>{a.events.map((e,i)=><p key={i}>{date(e.created_at)} · {({hint:'查看提示',card_read:'阅读知识卡',independent_correct:'独立完成',needs_remediation:'需要补学'}[e.kind]??e.kind)}{e.kind==='hint'?` · 第 ${e.payload.level} 级`:''}</p>)}</div>:<p className="muted">暂无事件记录</p>}]}/></section>
  </>}</State></>;
}

export function Cases() {
  const query=useQuery({queryKey:['cases'],queryFn:()=>api<Case[]>('/teacher/review-cases')});
  return <><PageTitle title="评价复核" description="核对学生异议，保留原评价并说明每一次修订的依据。"/><State query={query}><Table rowKey="id" dataSource={query.data??[]} pagination={{pageSize:10}} scroll={{x:750}} columns={[
    {title:'题目',dataIndex:'prompt'},{title:'异议说明',dataIndex:'reason'},{title:'状态',dataIndex:'status',render:v=><Status value={v}/>},{title:'当前得分',render:(_,r)=>r.evaluation.score},{title:'处理意见',dataIndex:'resolution',render:v=>v||'—'},{title:'操作',render:(_,r)=><Link to={'/teacher/attempts/'+r.attempt_id+(r.status==='open'?'?case='+r.id:'')}><Button>{r.status==='open'?'进入复核':'查看记录'}</Button></Link>},
  ]}/></State></>;
}

type Account = Contracts['AccountOutput'];
export function AdminUsers() {
  const query=useQuery({queryKey:['users'],queryFn:()=>api<Account[]>('/admin/users')});
  const classes=useQuery({queryKey:['classes'],queryFn:()=>api<{id:string;name:string}[]>('/classes')});
  const [open,setOpen]=useState(false);
  const [form]=Form.useForm();
  const {busy,run}=useRun();
  return <><PageTitle title="账号管理" description="管理本机构账号和角色；教师评分权限与机构管理权限分别授予。" action={<Button type="primary" icon={<PlusOutlined aria-hidden/>} onClick={()=>{form.resetFields();setOpen(true)}}>创建账号</Button>}/><State query={query}><Table rowKey="id" dataSource={query.data??[]} columns={[{title:'姓名',dataIndex:'name'},{title:'账号',dataIndex:'username'},{title:'角色',dataIndex:'roles',render:(v:string[])=>v.map(r=><Tag key={r}>{({student:'学生',teacher:'教师',admin:'机构管理员'}[r]??r)}</Tag>)},{title:'状态',dataIndex:'active',render:v=><Tag color={v?'green':'red'}>{v?'正常':'已停用'}</Tag>}]}/></State>
    <Modal title="创建机构账号" open={open} onCancel={()=>setOpen(false)} footer={null}><Form form={form} layout="vertical" requiredMark={false} onFinish={values=>run(async()=>{const result=await api('/admin/users','POST',values);setOpen(false);return result},'账号已创建')}>
      <Form.Item name="name" label="姓名" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="username" label="登录账号" rules={[{required:true},{pattern:/^[a-zA-Z0-9_.-]{3,80}$/,message:'使用3至80位字母、数字、点、横线或下划线'}]}><Input autoComplete="off"/></Form.Item><Form.Item name="password" label="初始密码" rules={[{required:true},{min:10,message:'密码至少10位'}]}><Input.Password autoComplete="new-password"/></Form.Item><Form.Item name="roles" label="角色" rules={[{required:true}]}><Select mode="multiple" options={[{value:'student',label:'学生'},{value:'teacher',label:'教师'},{value:'admin',label:'机构管理员'}]}/></Form.Item><Form.Item name="class_id" label="所属班级" rules={[{required:true}]}><Select options={classes.data?.map(c=>({value:c.id,label:c.name}))}/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>创建账号</Button>
    </Form></Modal>
  </>;
}
