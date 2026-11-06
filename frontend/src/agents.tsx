import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Alert, Button, Collapse, Form, InputNumber, Select, Space, Tag } from 'antd';
import { api, key, type Evidence } from './api';
import { Sources, useRun } from './ui';

export type AgentRun={id:string;purpose:string;state:string;stage:string;error_code:string;model:string;metrics:Record<string,unknown>;output:{
  explanation?:string;candidate_cause?:string;option_analysis?:Record<string,string>;knowledge_gaps?:string[];learning_advice?:string[];
  clarifying_questions?:string[];sources?:Evidence[];coverage?:string;question_ids?:string[];practice_id?:string;issues?:string[];
  available_chunks?:number;sampled_chunks?:number;parts?:number[];feedback?:string;
}};

const errorNames:Record<string,string>={MODEL_NOT_CONFIGURED:'尚未配置真实模型',MODEL_TIMEOUT:'模型响应超时，已保存进度',MODEL_RATE_LIMIT:'模型服务限流',MODEL_TEMPORARY_ERROR:'模型暂时不可用',MODEL_AUTH_FAILED:'模型鉴权失败',MODEL_INSUFFICIENT_BALANCE:'模型账户余额不足',MODEL_OUTPUT_INVALID:'模型返回格式异常',MODEL_CONNECTION_ERROR:'无法连接模型服务',GENERATION_VALIDATION_FAILED:'内容未通过答案或原文校验，未加入可用题库',SOURCE_NOT_ENABLED:'原文尚未启用',CONTENT_UNAVAILABLE:'原文已撤回或暂不可用',ACCESS_REVOKED:'任务授权已变化',NO_EVIDENCE:'没有可用原文依据',EMBEDDING_MODEL_UNAVAILABLE:'本地检索模型未就绪',INDEX_NOT_READY:'资料索引尚未就绪',WORKER_INTERRUPTED:'任务被中断，进度已保留',JOB_FAILED:'任务执行失败，原始资料与作答仍保留'};
export const pendingAgent=(r:AgentRun)=>['queued','running'].includes(r.state);

export function AgentResult({item}:{item:AgentRun}){
  const {run,busy}=useRun();
  const o=item.output;
  const resume=['DEEPTUTOR_TIMEOUT','DEEPTUTOR_RECONNECT_FAILED','WORKER_INTERRUPTED'].includes(item.error_code)&&item.model.startsWith('deeptutor:');
  const uncertain=item.error_code==='EXECUTION_UNCERTAIN';
  const errorText=uncertain?'未确认 DeepTutor 是否已接收任务，请联系管理员核对。':resume?'DeepTutor 暂未返回结果，已保存进度。':errorNames[item.error_code];
  return <div className="agent-result" aria-live="polite">
    <Space wrap><Tag color={item.state==='succeeded'?'green':item.state==='failed'?'red':'processing'}>{item.stage}</Tag><span className="muted">{item.model}</span></Space>
    {pendingAgent(item)&&<p>正在处理，刷新或稍后回来可继续查看，不必重复提交。</p>}
    {item.error_code&&<Alert type="warning" showIcon message={errorText??'处理未完成，请重试或联系教师'} description={o.issues?.join('；')}/>}
    {o.explanation&&<p className="preserve-text">{o.explanation}</p>}
    {o.candidate_cause&&<p><strong>可能错因：</strong>{o.candidate_cause}</p>}
    {!!Object.keys(o.option_analysis??{}).length&&<div><h4>选项辨析</h4>{Object.entries(o.option_analysis??{}).map(([label,text])=><p key={label}><strong>{label}：</strong>{text}</p>)}</div>}
    {!!o.knowledge_gaps?.length&&<div><h4>需要补充的知识</h4><ul>{o.knowledge_gaps.map((s,i)=><li key={i}>{s}</li>)}</ul></div>}
    {!!o.learning_advice?.length&&<div><h4>学习建议</h4><ol>{o.learning_advice.map((s,i)=><li key={i}>{s}</li>)}</ol></div>}
    {!!o.clarifying_questions?.length&&<div><h4>还可回想这些问题</h4>{o.clarifying_questions.map((s,i)=><p key={i}>{s}</p>)}</div>}
    {o.coverage&&<p>{o.coverage}</p>}
    {!!o.question_ids?.length&&<p>本批已校验 {o.question_ids.length} 道新题。{o.available_chunks!==undefined&&`资料共 ${o.available_chunks} 个页段，本批提取使用 ${o.sampled_chunks} 个代表页段，题目另按知识点检索依据。`}</p>}
    {!!o.sources?.length&&<Collapse items={[{key:'sources',label:'核对引用与原页',children:<Sources items={o.sources}/>}]}/>}
    {o.practice_id&&<Link to={'/practice/'+o.practice_id}><Button type="primary">开始针对性练习</Button></Link>}
    {item.state==='failed'&&!uncertain&&<Button loading={busy} onClick={()=>run(()=>api('/agent-runs/'+item.id+'/retry','POST',{},key()),resume?'正在恢复原运行':'已提交重试')}>{resume?'恢复原运行':'重试任务'}</Button>}
    {!!Object.keys(item.metrics).length&&<Collapse items={[{key:'metrics',label:'查看调用记录',children:<p>结构化调用 {Number(item.metrics.calls??0)} 次{item.metrics.native_calls!=null&&' · 原生出题 '+Number(item.metrics.native_calls)+' 次'} · {item.metrics.total_tokens==null?'用量未返回':Number(item.metrics.total_tokens)+' tokens'}{item.metrics.estimated_cost_usd!=null&&' · 估算 $'+Number(item.metrics.estimated_cost_usd).toFixed(6)+'（以实际账单为准）'}</p>}]}/>}
  </div>;
}

type Processing={enabled:boolean;parsed:boolean;document_state:string;version_status:string;chapters:{position:number;heading:string}[];runs:AgentRun[]};
type GenSettings={single:number;multiple:number;essay:number;chapters:number[];supplement_ids:string[]};
export function GenerationPanel({versionId,teacher}:{versionId:string;teacher:boolean}){
  const query=useQuery({queryKey:['processing',versionId],queryFn:()=>api<Processing>('/content/sources/'+versionId+'/processing'),refetchInterval:q=>!q.state.data?.parsed||q.state.data.runs.some(pendingAgent)?2000:false});
  const index=useQuery({queryKey:['index',versionId],queryFn:()=>api<{state:string;backend?:string}>('/content/indexes/'+versionId),refetchInterval:q=>q.state.data?.state==='ready'?false:3000});
  const sources=useQuery({queryKey:['supplements'],queryFn:()=>api<{items:{id:string;title:string;enabled:boolean}[]}>('/content/sources?page_size=100')});
  const [form]=Form.useForm<GenSettings>();
  const [expanded,setExpanded]=useState(false);
  const {run,busy}=useRun();
  const p=query.data;
  const pending=p?.runs.some(pendingAgent);
  async function enable(values:GenSettings){await run(()=>api('/content/sources/'+versionId+(p?.enabled?'/generate':'/enable'),'POST',values,key()),'已提交资料生成任务');}
  return <section className="panel section-space generation-panel"><div className="section-heading"><div><h2>原文与 Agent 出题</h2><p>启用一次原文，自动提取知识卡、生成题目并核对答案。无需提交审核说明。</p></div><Tag color={p?.enabled?'green':'default'}>{p?.enabled?'原文已启用':'原文未启用'}</Tag></div>
    {query.error&&<Alert type="error" message={query.error.message}/>}
    {!p?.parsed&&<Alert type="info" message="正在解析资料，请等待原页与正文准备完成"/>}
    {p?.parsed&&index.data?.backend==='deeptutor'?<p>开始生成后，DeepTutor 会为本次选定的资料建立索引。</p>:p?.parsed&&index.data?.state!=='ready'&&<p>正在建立原文索引，就绪后可启用。</p>}
    {teacher&&p?.version_status!=='withdrawn'&&<Form form={form} initialValues={{single:6,multiple:4,essay:2,chapters:[],supplement_ids:[]}} onFinish={enable}>
      <Space wrap className="generation-counts">{[['single','单选题'],['multiple','多选题'],['essay','分析题']].map(([name,label])=><Form.Item key={name} name={name} label={label}><InputNumber aria-label={label} min={0} max={30} precision={0}/></Form.Item>)}</Space>
      <Form.Item noStyle shouldUpdate>{()=>{const values=form.getFieldsValue();return <p className="muted">共 {Number(values.single??0)+Number(values.multiple??0)+Number(values.essay??0)} 题，单批1至30题；数量有限，不代表覆盖整本教材。</p>}}</Form.Item>
      <Button type="link" onClick={()=>setExpanded(!expanded)}>{expanded?'收起范围设置':'选择章节与补充资料（可选）'}</Button>
      <div style={{display:expanded?'block':'none'}}><Form.Item name="chapters" label="章节 / 原文页段"><Select mode="multiple" placeholder="默认从全部原文中选取代表内容" options={p?.chapters.map(c=>({value:c.position,label:`${c.position}. ${c.heading}`}))}/></Form.Item><Form.Item name="supplement_ids" label="补充资料"><Select mode="multiple" placeholder="只使用教师已启用的资料" options={sources.data?.items.filter(s=>s.enabled&&s.id!==versionId).map(s=>({value:s.id,label:s.title}))}/></Form.Item></div>
      <Button type="primary" htmlType="submit" loading={busy} disabled={!p?.parsed||index.data?.state!=='ready'||pending}>{pending?'Agent 正在处理':p?.enabled?'再生成一批':'启用并生成'}</Button>
    </Form>}
    {p?.runs.map(r=><AgentResult key={r.id} item={r}/>)}
    {p?.runs.some(r=>r.state==='succeeded')&&<Link to="/assignments"><Button className="section-space">选择生成题目，布置作业</Button></Link>}
  </section>;
}
