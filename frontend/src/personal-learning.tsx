import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Collapse, Form, InputNumber, Pagination, Select, Space, Tag } from 'antd';
import { Link } from 'react-router-dom';
import { apiV2, key } from './api';
import { Blank, State, useRun } from './ui';

type Job = {id:string;state:string;error:string;result?:{assessment_id?:string|null;diagnosis?:string|null}};
const waiting = (job?:Job|null) => job?.state === 'queued' || job?.state === 'running';
const sources:Record<string,string> = {guided:'助教检查',concentrated:'集中练习',chapter:'历史章节练习',paper:'真题 / 模考',legacy:'其他自主练习',review:'复习'};
const states:Record<string,string> = {correct:'正确',incorrect:'未达标',unanswered:'未作答',pending:'待 AI 评价',evaluation_failed:'评价未完成',ungraded:'未判定'};
const kinds = [['single','单选题'],['multiple','多选题'],['essay','分析题']] as const;
type Values = Record<typeof kinds[number][0], number> & {scope_id?:string};

export function ConcentratedPractice({projectId,disabled}:{projectId:string;disabled:boolean}) {
  const base='/learning-projects/'+projectId;
  const config=useQuery({queryKey:['concentrated-config',projectId],
    queryFn:()=>apiV2<{ready:boolean;options:{id:string;label:string}[]}>(base+'/concentrated-practice')});
  const cacheKey='concentrated-run:'+projectId;
  const [runId,setRunId]=useState<string|undefined>(()=>sessionStorage.getItem(cacheKey)??undefined);
  const pending=useRef<{body:string;id:string}|undefined>(undefined);
  const {run,busy}=useRun();
  const job=useQuery({queryKey:['personal-run',projectId,runId], enabled:!!runId,
    queryFn:()=>apiV2<Job>(base+'/personal-runs/'+runId),
    refetchInterval:q=>waiting(q.state.data)?2000:false});
  return <State query={config}><Form layout="vertical" initialValues={{single:3,multiple:0,essay:0}} onFinish={async(values:Values)=>{
    if(values.single+values.multiple+values.essay<1||values.single+values.multiple+values.essay>10)return;
    const body=JSON.stringify(values);
    if(pending.current?.body!==body)pending.current={body,id:key()};
    const reply=await run(()=>apiV2<{run_id:string}>(base+'/concentrated-practice','POST',values,pending.current!.id));
    if(reply){setRunId(reply.run_id);sessionStorage.setItem(cacheKey,reply.run_id);pending.current=undefined;}
  }}>
    <Form.Item label="出题范围（可选）" name="scope_id"><Select allowClear placeholder="当前项目范围"
      options={config.data?.options.map(o=>({value:o.id,label:o.label}))}/></Form.Item>
    {kinds.map(([name,label])=><Form.Item key={name} label={label} name={name}
      rules={[{required:true,type:'integer',min:0,max:10}]}><InputNumber min={0} max={10}/></Form.Item>)}
    <p>合计生成 1–10 道新题。不限时，可以保存草稿，交卷后查看解析。</p>
    {config.data?.ready===false&&<Alert type="info" message="请先补齐项目资料并完成索引。"/>}
    <Form.Item shouldUpdate noStyle>{({getFieldsValue})=>{
      const v=getFieldsValue();
      const total=(v.single??0)+(v.multiple??0)+(v.essay??0);
      return <Button htmlType="submit" type="primary" loading={busy} disabled={disabled||!config.data?.ready||total<1||total>10||waiting(job.data)||!!runId&&job.isPending}>生成练习</Button>;
    }}</Form.Item>
  </Form>
    {runId&&<State query={job}>
      {waiting(job.data)&&<p role="status">助教正在生成并核对题目…</p>}
      {job.data?.state==='failed'&&<Alert type="warning" message={job.data.error||'生成失败'}
        action={<Button disabled={disabled} loading={busy} onClick={async()=>{
          await run(()=>apiV2(base+'/personal-runs/'+runId+'/retry','POST'));void job.refetch();
        }}>重试生成</Button>}/>}
      {job.data?.result?.assessment_id&&<p><Link to={'/learning/assessments/'+job.data.result.assessment_id}><Button type="primary">打开集中练习</Button></Link></p>}
    </State>}
  </State>;
}

type Attempt = {id:string;created_at:string;source:string;state:string;prompt:string;kind:string;options:Record<string,string>;
  answer:string;reference:string;explanation:string;feedback:string;assessment_id:string|null;diagnosis?:Job|null};
type History = {items:Attempt[];total:number;partial:boolean};

export function ProjectAttempts({projectId,mistakes=false,readOnly=false,initialSource}:{projectId:string;mistakes?:boolean;readOnly?:boolean;initialSource?:string}) {
  const [source,setSource]=useState(initialSource);
  const [page,setPage]=useState(1);
  const [started,setStarted]=useState(false);
  const base='/learning-projects/'+projectId;
  const {run,busy}=useRun();
  const params=new URLSearchParams({offset:String((page-1)*20),mistakes:String(mistakes)});
  if(source)params.set('source',source);
  const query=useQuery({queryKey:['project-attempts',projectId,mistakes,source,page],
    queryFn:()=>apiV2<History>(base+'/attempt-history?'+params),
    refetchInterval:q=>started||q.state.data?.items.some(a=>waiting(a.diagnosis)||a.state==='pending')?2500:false});
  async function diagnose(item:Attempt){
    setStarted(true);
    try {
      if(item.diagnosis?.state==='failed'){
        await run(()=>apiV2(base+'/personal-runs/'+item.diagnosis!.id+'/retry','POST'));
      }else{
        await run(()=>apiV2(base+'/attempt-diagnoses','POST',{attempt_id:item.id},key()));
      }
      await query.refetch();
    }finally{setStarted(false);}
  }
  return <>
    <Select allowClear aria-label="作答来源" placeholder="全部来源" value={source} style={{minWidth:160,marginBottom:12}}
      options={Object.entries(sources).map(([value,label])=>({value,label}))} onChange={v=>{setSource(v);setPage(1);}}/>
    <State query={query}>
      {query.data?.partial&&<Alert type="warning" message="助教作答暂不可读取，已显示可读取的记录。"
        action={<Button onClick={()=>void query.refetch()}>重试</Button>}/>}
      {query.data?.items.length?<Collapse items={query.data.items.map(item=>({
        key:item.id,label:<Space wrap><Tag>{sources[item.source]||item.source}</Tag><Tag>{states[item.state]||item.state}</Tag>
          <span>{item.prompt.slice(0,90)}</span><small>{new Date(item.created_at).toLocaleString('zh-CN')}</small></Space>,
        children:<>
          <p className="preserve-text">{item.prompt}</p>
          {Object.entries(item.options).map(([k,v])=><p key={k}>{k}. {v}</p>)}
          <p className="preserve-text"><strong>你的作答：</strong>{item.answer||'未作答'}</p>
          {item.reference&&<p className="preserve-text"><strong>参考答案：</strong>{item.reference}</p>}
          {item.explanation&&<p className="preserve-text">{item.explanation}</p>}
          {item.feedback&&<p className="preserve-text"><strong>反馈：</strong>{item.feedback}</p>}
          {item.assessment_id&&<Link to={'/learning/assessments/'+item.assessment_id}>查看整卷</Link>}
          {mistakes&&<div className="section-space">
            {!readOnly&&!item.diagnosis?.result?.diagnosis&&<Button loading={busy||waiting(item.diagnosis)}
              onClick={()=>void diagnose(item)}>{item.diagnosis?.state==='failed'?'重试 AI 诊断':'AI 诊断'}</Button>}
            {item.diagnosis?.state==='failed'&&<Alert type="warning" message={item.diagnosis.error||'诊断未完成'}/>}
            {item.diagnosis?.result?.diagnosis&&<p className="preserve-text"><strong>AI 诊断：</strong>{item.diagnosis.result.diagnosis}</p>}
          </div>}
        </>,
      }))}/>:<Blank description={mistakes?'此项目暂无可诊断的自主错题。':'此项目暂无已提交的作答。'}/>}
      {!!query.data?.total&&<Pagination current={page} pageSize={20} total={query.data.total} onChange={setPage} showSizeChanger={false}/>}
    </State>
  </>;
}
