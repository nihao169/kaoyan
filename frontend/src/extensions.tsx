import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Alert, Button, Card, Collapse, Input, Select, Space, Table, Tag } from 'antd';
import { api, key, type Evidence, type Catalog } from './api';
import { PageTitle, Sources, State, useRun } from './ui';
import { AgentResult, type AgentRun } from './agents';

type AIRun={id:string;purpose:string;state:string;model:string;attempt_id:string|null;error_code:string;result:{explanation?:string;candidate_cause?:string;reliable?:boolean;dimensions?:Record<string,unknown>[];sources?:Evidence[];notice?:string};metrics:Record<string,unknown>};
const purposes:Record<string,string>={question:'当前题目答疑',hint:'递进提示',cause:'候选错因',evaluation:'分析题辅助评价',lesson:'教案草稿'};
const errors:Record<string,string>={MODEL_NOT_CONFIGURED:'学习助手尚未配置',MODEL_AUTH_FAILED:'密钥鉴权失败',MODEL_INSUFFICIENT_BALANCE:'模型账户余额不足',MODEL_TIMEOUT:'模型调用超时',MODEL_RATE_LIMIT:'模型请求限流',SOURCE_NOT_ENABLED:'请教师先启用原文并生成内容',NO_EVIDENCE:'没有可用的已启用教师原文',INDEX_NOT_READY:'资料索引尚未完成',EMBEDDING_MODEL_UNAVAILABLE:'本地向量模型未就绪',MODEL_OUTPUT_INVALID:'模型返回格式不符合要求'};

Object.assign(errors,{CONTENT_UNAVAILABLE:'依据资料已撤回或访问权限变化，请联系教师',MODEL_CONFIGURATION_CHANGED:'模型配置已变化，请发起新任务',MODEL_CONNECTION_ERROR:'无法连接模型服务，请检查网络后重试',MODEL_REQUEST_REJECTED:'模型服务拒绝请求，请检查服务端配置',INVALID_CITATION:'引用未通过真实性检查，请转教师核对',WORKER_INTERRUPTED:'任务执行被中断，可以重试',ACCESS_REVOKED:'当前访问权限已变化，请重新登录'});
const documentErrors:Record<string,string>={DOCX_CONVERTER_REQUIRED:'未找到文档转换工具，请先准备 LibreOffice',DOCX_CONVERSION_FAILED:'DOCX 转换失败，请检查文件后重试',DOCX_CONVERSION_TIMEOUT:'文档转换超时，可以重试或改用文本 PDF',PDF_ENCRYPTED:'PDF 已加密，请使用可读取的文件',SCANNED_PAGE_OCR_UNSUPPORTED:'发现扫描页，当前版本不支持 OCR',DOCUMENT_EMPTY:'文件没有可提取的正文',DOCUMENT_PAGE_LIMIT:'文件超过 1000 页限制',DOCUMENT_INVALID:'文件损坏或无法解析',DOCUMENT_CHANGED:'转换期间文件版本发生变化，请重新提交'};

function AIResults({runs}:{runs:AIRun[]}) {
  const {run,busy}=useRun();
  return <>{runs.map(r=><Card key={r.id} size="small" className="section-space" title={<Space><span>{purposes[r.purpose]}</span><Tag>{({queued:'排队中',running:'处理中',succeeded:'已完成',failed:'失败'} as Record<string,string>)[r.state]??r.state}</Tag></Space>}>
    {r.error_code&&<Alert type="warning" message={errors[r.error_code]??r.error_code}/>}
    {r.result.explanation&&<p className="preserve-text">{r.result.explanation}</p>}
    {r.result.candidate_cause&&<Tag>候选错因：{r.result.candidate_cause}</Tag>}
    {!!r.result.dimensions?.length&&<ul>{r.result.dimensions.map((d,i)=><li key={i}>{Object.entries(d).map(([k,v])=>`${k}：${String(v)}`).join('；')}</li>)}</ul>}
    {!!r.result.sources?.length&&<Collapse items={[{key:'evidence',label:'核对引用与原页',children:<Sources items={r.result.sources}/>}]} />}
    <p className="small-note">{r.result.notice??'正式成绩以规则或教师评价为准。'} · {r.model}</p>
    {!!Object.keys(r.metrics).length&&<Collapse items={[{key:'metrics',label:'查看调用记录',children:<div><p>调用 {Number(r.metrics.calls??0)} 次 · 耗时 {(Number(r.metrics.duration_ms??0)/1000).toFixed(1)} 秒 · {Number(r.metrics.total_tokens??0)} tokens</p><p>估算费用 ${Number(r.metrics.estimated_cost_usd??0).toFixed(6)}，以实际账单为准。</p><small>价格依据：{String(r.metrics.price_version??'尚未记录')}</small></div>}]} />}
    {r.state==='failed'&&<Button loading={busy} onClick={()=>run(()=>api('/ai/requests/'+r.id+'/retry','POST'))}>重试此任务</Button>}
  </Card>)}</>;
}

export function AILearning({attemptId,draft,essay,hintLevel,beforeRun,afterRun}:{attemptId:string;draft:boolean;essay:boolean;hintLevel:number;beforeRun:()=>Promise<unknown>;afterRun:()=>unknown}) {
  const [question,setQuestion]=useState('');
  const [level,setLevel]=useState(Math.min(4,hintLevel+1));
  const {run,busy}=useRun();
  const query=useQuery({queryKey:['ai-requests',attemptId],queryFn:()=>api<AIRun[]>('/ai/requests?attempt_id='+attemptId),refetchInterval:q=>q.state.data?.some(r=>['queued','running'].includes(r.state))?2000:false});
  const refreshed=useRef(new Set<string>());
  useEffect(()=>{const completed=(query.data??[]).filter(r=>['succeeded','failed'].includes(r.state)&&!refreshed.current.has(r.id));if(completed.length){completed.forEach(r=>refreshed.current.add(r.id));afterRun()}},[query.data,afterRun]);
  useEffect(()=>{setLevel(Math.min(4,hintLevel+1))},[hintLevel]);
  async function start(purpose:string){await run(async()=>{await beforeRun();const result=await api('/ai/requests','POST',{purpose,attempt_id:attemptId,question,level},key());await afterRun();return result},'AI 任务已提交');}
  return <Card title="学习助手"><p>围绕当前题目提问，引用可打开原页。AI 帮助会记录为辅助作答。</p>
    <Input.TextArea aria-label="当前题目疑问" rows={3} value={question} onChange={e=>setQuestion(e.target.value)} maxLength={2000} placeholder="描述卡住的地方，或直接选择分析功能"/>
    <Space wrap className="section-space"><Button loading={busy} onClick={()=>start('question')}>带依据答疑</Button>{draft?<><Select aria-label="AI提示级别" value={level} onChange={setLevel} options={[1,2,3,4].map(n=>({value:n,label:`第 ${n} 级`,disabled:n>hintLevel+1}))}/><Button loading={busy} onClick={()=>start('hint')}>获取 AI 提示</Button></>:<Link to={'/mistakes?attempt='+attemptId}><Button>进入错题诊断</Button></Link>}</Space>
    <Button block loading={busy} onClick={()=>run(()=>api('/attempts/'+attemptId+'/referrals','POST',{text:question.trim()||'希望教师帮助核对当前题目、依据及学习困难'}),'已提交教师处理')}>转教师帮助</Button>
    <AIResults runs={query.data??[]}/>
  </Card>;
}

export function KnowledgeStatus(){
  const query=useQuery({queryKey:['knowledge-status'],queryFn:()=>api<{id:string;name:string;state:string;requires:string[]}[]>('/knowledge/status')});
  return <><PageTitle title="知识点诊断" description="依据真实作答显示有限学习证据；未覆盖的知识点保留待诊断。"/><State query={query}><Table rowKey="id" dataSource={query.data??[]} columns={[{title:'知识点',dataIndex:'name'},{title:'当前证据',dataIndex:'state'},{title:'前置知识',render:(_,r)=>r.requires.map(id=>query.data?.find(k=>k.id===id)?.name??id).join('、')||'无'}]}/></State></>;
}

type Referral={id:string;attempt_id:string;prompt:string;reason:string;state:string;response:string};
export function Referrals({teacher=false}:{teacher?:boolean}){
  const query=useQuery({queryKey:['referrals'],queryFn:()=>api<Referral[]>('/teaching/referrals')});
  const [answers,setAnswers]=useState<Record<string,string>>({});
  const {run,busy}=useRun();
  return <><PageTitle title={teacher?'学习困难转办':'教师帮助'} description="保留学生的困难描述与教师回复，评价异议仍在原评分流程中处理。"/><State query={query}>{query.data?.map(r=><Card key={r.id} className="section-space" title={r.prompt} extra={<Tag>{r.state==='open'?'待处理':'已回复'}</Tag>}><p>{r.reason}</p>{r.response&&<p className="preserve-text">教师回复：{r.response}</p>}<Link to={teacher?'/teacher/attempts/'+r.attempt_id:'/history'}>查看作答记录</Link>{teacher&&r.state==='open'&&<><Input.TextArea aria-label="教师回复" value={answers[r.id]??''} onChange={e=>setAnswers({...answers,[r.id]:e.target.value})}/><Button loading={busy} disabled={!answers[r.id]?.trim()} onClick={()=>run(()=>api('/teaching/referrals/'+r.id+'/resolve','POST',{text:answers[r.id]}),'回复已保存')}>保存并完成转办</Button></>}</Card>)}</State></>;
}

type Lesson={id:string;request_id:string;body:string;revision:number};
export function Lessons(){
  const catalog=useQuery({queryKey:['catalog'],queryFn:()=>api<Catalog>('/catalog')});
  const runs=useQuery({queryKey:['ai-lessons'],queryFn:()=>api<AIRun[]>('/ai/requests'),refetchInterval:q=>q.state.data?.some(r=>['queued','running'].includes(r.state))?2000:false});
  const lessons=useQuery({queryKey:['lessons',runs.data],queryFn:()=>api<Lesson[]>('/teacher/lessons')});
  const [knowledge,setKnowledge]=useState<string>();
  const [edits,setEdits]=useState<Record<string,string>>({});
  const {run,busy}=useRun();
  return <><PageTitle title="AI 备课" description="使用审核内容生成教案草稿，教师编辑保存后仍不自动发布。"/><Space wrap><Select aria-label="备课知识点" style={{minWidth:280}} placeholder="选择知识点" value={knowledge} onChange={setKnowledge} options={catalog.data?.knowledge.map(k=>({label:k.name,value:k.id}))}/><Button loading={busy} disabled={!knowledge} onClick={()=>run(()=>api('/ai/requests','POST',{purpose:'lesson',knowledge_id:knowledge},key()),'备课任务已提交')}>生成教案草稿</Button></Space>
    <AIResults runs={(runs.data??[]).filter(r=>r.purpose==='lesson')}/>{lessons.data?.map(l=><Card key={l.id} title={`可编辑教案 · 修订 ${l.revision}`} className="section-space"><Input.TextArea aria-label="教案正文" rows={12} value={edits[l.id]??l.body} onChange={e=>setEdits({...edits,[l.id]:e.target.value})}/><Button loading={busy} onClick={()=>run(()=>api('/teacher/lessons/'+l.id,'PUT',{text:edits[l.id]??l.body,revision:l.revision}),'教案修订已保存')}>保存教案</Button></Card>)}</>;
}

export function AISettings(){
  const status=useQuery({queryKey:['ai-status'],queryFn:()=>api<{configured:boolean;model:string;provider:string;price_version:string|null}>('/ai/status')});
  const [result,setResult]=useState('');
  const {run,busy}=useRun();
  return <><PageTitle title="AI 服务状态" description="模型凭据由服务端管理。"/><State query={status}><Card><Tag color={status.data?.configured?'green':'orange'}>{status.data?.configured?'已配置，待测试连接':'未配置'}</Tag><p>{status.data?.provider} · {status.data?.model}</p><p>{status.data?.provider==='DeepTutor'?'通过当前教学服务测试连接。':'填写 MODEL_API_KEY 后重启服务，再测试真实连接。'}</p>{status.data?.price_version&&<p>费用估算版本：{status.data.price_version}</p>}<Button loading={busy} onClick={()=>run(async()=>{const r=await api<{connected:boolean}>('/ai/connection-test','POST');setResult(r.connected?'真实连接成功':'连接返回未通过');return r})}>测试真实连接</Button>{result&&<Alert type="info" message={result}/>}</Card></State></>;
}

type Doc={filename:string;state:string;error_code:string;confirmed:boolean;pages:{number:number;width:number;height:number;blocks:{text:string;bbox:number[]}[]}[];preview_url:string|null;original_url:string};
export function DocumentPreview({versionId,teacher}:{versionId:string;teacher:boolean}){
  const client=useQueryClient();
  const query=useQuery({queryKey:['document',versionId],queryFn:()=>api<Doc|null>('/sources/versions/'+versionId+'/document'),refetchInterval:q=>q.state.data?.state==='queued'?2000:false});
  const requested=Number(new URLSearchParams(window.location.search).get('page'))||1;
  const [page,setPage]=useState(requested);
  const chunk=new URLSearchParams(window.location.search).get('chunk')??'';
  const {run,busy}=useRun();
  const d=query.data;
  useEffect(()=>{if(d?.state==='parsed')client.invalidateQueries({queryKey:['source',versionId]})},[d?.state,versionId,client]);
  if(!d)return null;
  return <section className="panel section-space"><h2>原页与解析对照</h2><Space wrap><Tag>{d.state}</Tag><span>{d.filename}</span><a href={d.original_url} target="_blank" rel="noreferrer">打开原文件</a>{d.preview_url&&<a href={d.preview_url+'#page='+page} target="_blank" rel="noreferrer">打开固定版式 PDF</a>}</Space>
    {d.error_code&&<Alert type="warning" message={documentErrors[d.error_code]??'解析未完成，请联系教师核对文件'} description="扫描件暂不支持 OCR；DOCX 需要本机 LibreOffice 转换器。"/>}
    {d.state==='parsed'&&<><Select aria-label="原页页码" value={page} onChange={setPage} options={d.pages.map(p=>({value:p.number,label:`第 ${p.number} 页`}))}/><div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(280px,1fr))',gap:24,marginTop:16}}><img style={{width:'100%'}} alt={`原文第 ${page} 页`} src={`/api/v1/sources/versions/${versionId}/pages/${page}?chunk=${encodeURIComponent(page===requested?chunk:'')}`}/><div>{d.pages.find(p=>p.number===page)?.blocks.map((b,i)=><p key={i} style={{whiteSpace:'pre-wrap',background:chunk?'#fff8d8':undefined}}>{b.text}</p>)}</div></div></>}
    {teacher&&d.state==='failed'&&<Button loading={busy} onClick={()=>run(()=>api('/documents/'+versionId+'/retry','POST'))}>重试解析</Button>}
    {teacher&&d.state!=='queued'&&<label style={{display:'block',marginTop:16}}>上传修订原文件（PDF / DOCX，最多50MB）<input aria-label="修订原文件" type="file" accept=".pdf,.docx" onChange={e=>{const file=e.target.files?.[0];if(file)run(async()=>{const body=new FormData();body.append('file',file);return api('/documents/'+versionId+'/original','POST',body)},'已提交修订文件解析')}}/></label>}
  </section>;
}

export function TeacherLearningChain({attemptId}:{attemptId:string}){
  type Chain={remediation:{id:string;cause:string}|null;verification:{id:string;status:string;answer:string[];response_text:string;hint_level:number}|null;agents:AgentRun[];practices:{id:string;state:string;attempts:{id:string;grading_state:string;answer:string[];response_text:string;hint_level:number}[]}[];reviews:{stage:number;due_at:string;state:string;task_id:string|null}[];ai:AIRun[];events:{kind:string;payload:Record<string,unknown>;created_at:string}[]};
  const query=useQuery({queryKey:['learning-chain',attemptId],queryFn:()=>api<Chain>(`/teacher/attempts/${attemptId}/learning-chain`)});
  const {run,busy}=useRun();
  const data=query.data;
  return <section className="panel section-space"><h2>补学、验证与 AI 证据</h2><State query={query}>{data?.remediation&&<Space wrap><span>确认错因：{data.remediation.cause}</span><Select aria-label="教师修正错因" placeholder="选择修正错因" style={{minWidth:180}} disabled={busy} options={['概念混淆','原理适用','材料理解','论证表达','审题','时间管理'].map(c=>({value:c,label:c}))} onChange={cause=>run(()=>api('/teacher/remediations/'+data.remediation!.id+'/cause','POST',{cause}),'错因修正及补学路径已保存')}/></Space>}<AIResults runs={data?.ai??[]}/><Collapse items={[{key:'chain',label:'新题验证、复习与错因修订',children:<>
    {data?.agents.map(a=><AgentResult key={a.id} item={a}/>)}
    {data?.practices.map(p=><div key={p.id}><h3>针对性练习 · {p.state==='submitted'?'已提交':'作答中'}</h3>{p.attempts.map((a,i)=><p key={a.id}><Link to={'/teacher/attempts/'+a.id}>第 {i+1} 题：{a.grading_state}</Link> · {a.hint_level?'使用过提示':'未使用提示'} · {a.response_text||a.answer.join('、')||'暂无答案'}</p>)}</div>)}
    {data?.verification?<div><h3>历史新题验证</h3><p>{data.verification.response_text||data.verification.answer.join('、')} · {data.verification.hint_level?'使用过提示':'未使用提示'}</p><Link to={'/teacher/attempts/'+data.verification.id}>查看验证作答与评价</Link></div>:null}
    <Table rowKey={r=>String(r.stage)+r.due_at} pagination={false} dataSource={data?.reviews??[]} columns={[{title:'复习阶段',dataIndex:'stage'},{title:'安排时间',dataIndex:'due_at',render:v=>new Date(v).toLocaleString('zh-CN')},{title:'进度',dataIndex:'state',render:v=>({scheduled:'待复习',completed:'已完成',needs_remediation:'需补学',cancelled:'已取消'}[v as string]??v)}]}/>
    {data?.events.filter(e=>e.kind==='cause_changed').map((e,i)=><p key={i}>{new Date(e.created_at).toLocaleString('zh-CN')}：错因由“{String(e.payload.before)}”修订为“{String(e.payload.after)}”。</p>)}
  </>}]} /></State></section>;
}

export function IndexStatus({versionId}:{versionId:string}){
 const query=useQuery({queryKey:['index',versionId],queryFn:()=>api<{state:string;chunks:number;indexed:number}>('/content/indexes/'+versionId),refetchInterval:q=>q.state.data?.state==='not_ready'?5000:false});
 const {run,busy}=useRun();
 return <div className="section-space"><Tag color={query.data?.state==='ready'?'green':'orange'}>检索索引：{query.data?.state==='ready'?'就绪':'待建立'}</Tag><span>{query.data?.indexed??0} / {query.data?.chunks??0} 个片段已索引</span> <Button loading={busy} onClick={()=>run(()=>api('/content/indexes/'+versionId+'/rebuild','POST'),'已提交索引任务')}>重建索引</Button></div>;
}
