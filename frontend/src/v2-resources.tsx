import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Alert, App, Button, Collapse, Input, Modal, Select, Space, Tag } from 'antd';
import { apiV2, key } from './api';
import { Blank, State, useRun } from './ui';

export type Citation = {
  material_id: string; title: string; sha256: string; start: number; end: number;
  line_start: number; line_end: number; page: number | null; quote: string;
};
type Excerpt = Citation & { before: string; after: string };
type Topic = { code: string; chapter: string; title: string };
type Resource = {
  id: string; year: number; kind: 'syllabus' | 'past_paper' | 'simulated_paper'; title: string; edition: string;
  source: { title: string; url: string | null }; topics?: Topic[];
  question_count?: number; minutes?: number; total_points?: number;
};
type Reference = { year: number; title: string; publisher: string; url: string; isbn?: string };

function sourcePath(projectId:string, materialId:string) {
  return '/learning-projects/'+projectId+'/materials/'+materialId;
}

export function CitationList({ projectId, citations }: { projectId:string; citations:Citation[] }) {
  const {run,busy}=useRun();
  const [source,setSource]=useState<Excerpt>();
  async function open(c:Citation) {
    const params=new URLSearchParams({sha256:c.sha256,start:String(c.start),end:String(c.end)});
    const text=await run(()=>apiV2<Excerpt>(sourcePath(projectId,c.material_id)+'/excerpt?'+params));
    if(text)setSource(text);
  }
  return <><div className="v2-citations">{citations.map(c=><article className="v2-material" key={c.material_id+':'+c.start+':'+c.end}>
    <div><strong>{c.title} · {c.page?('第 '+c.page+' 页'):('第 '+c.line_start+'–'+c.line_end+' 行')}</strong>
      <blockquote>{c.quote}</blockquote></div><Button loading={busy} onClick={()=>void open(c)}>核对原文</Button>
  </article>)}</div><Modal title={source?.title} open={!!source} onCancel={()=>setSource(undefined)}
    footer={<Button onClick={()=>setSource(undefined)}>关闭原文</Button>}>
    {source&&<><p>第 {source.line_start}–{source.line_end} 行 · 资料版本 {source.sha256.slice(0,12)}</p>
      <p className="v2-excerpt">{source.before}<mark>{source.quote}</mark>{source.after}</p>
      {source.page&&<a target="_blank" rel="noreferrer" href={'/api/v2'+sourcePath(projectId,source.material_id)+'/original-pdf#page='+source.page}>打开 PDF 第 {source.page} 页</a>}</>}
  </Modal></>;
}

export function MaterialSearch({projectId}:{projectId:string}) {
  const [query,setQuery]=useState('');
  const results=useQuery({queryKey:['v2-material-search',projectId,query],enabled:!!query,
    queryFn:()=>apiV2<Citation[]>('/learning-projects/'+projectId+'/material-search?'+new URLSearchParams({q:query}))});
  return <section><h3>搜索资料全文</h3><Input.Search aria-label="搜索资料全文" enterButton="搜索" maxLength={500}
    placeholder="输入概念、关键词或原文短语" onSearch={value=>setQuery(value.trim())}/>
    {query&&<State query={results}>{results.data?.length?<CitationList projectId={projectId} citations={results.data}/>:
      <Blank description="没有检索到匹配片段。试试更具体的关键词。"/>}</State>}</section>;
}

const example = {
  kind:'syllabus',year:2027,edition:'v1',title:'考纲示例（请替换为实际内容）',source_title:'已获准使用的资料名称',
  rights_confirmed:false,topics:[{code:'example.1',chapter:'章节名称',title:'知识点名称',text:'在这里填入获准使用的考点说明。'}],
};
const paperExample = {
  kind:'past_paper',year:2026,edition:'v1',title:'试卷名称（请替换为实际内容）',source_title:'已获准使用的试卷和答案来源',
  rights_confirmed:false,minutes:180,questions:[{number:1,kind:'single',knowledge:'知识点',prompt:'录入原题题干',
    options:{A:'选项 A',B:'选项 B'},answer:['A'],explanation:'录入已核对的答案解析原文。',points:1}],
};

export function ExamResources({projectId,examYear,active}:{projectId:string;examYear:number;active:boolean}) {
  const {run,busy}=useRun();
  const {message,modal}=App.useApp();
  const navigate=useNavigate();
  const [open,setOpen]=useState(false);
  const [json,setJson]=useState('');
  const [year,setYear]=useState<number>();
  const path='/learning-projects/'+projectId+'/exam-resources';
  const query=useQuery({queryKey:['v2-exam-resources',projectId],queryFn:()=>apiV2<{resources:Resource[];references:Reference[];sample_available:boolean}>(path)});
  async function save() {
    let payload:unknown;
    try {payload=JSON.parse(json)} catch {message.error('资料清单不是有效的 JSON');return}
    const imported=await run(()=>apiV2<Resource>(path,'POST',payload,key()),'资料已导入本项目');
    if(imported){setOpen(false);setJson('');setYear(undefined)}
  }
  async function study(id:string,code:string) {
    const result=await run(()=>apiV2<{task_id:string}>(path+'/'+id+'/topics/'+encodeURIComponent(code)+'/study','POST'));
    if(result)navigate('/learning/session/'+result.task_id);
  }
  async function start(r:Resource,mode:'mock'|'practice') {
    const result=await run(()=>apiV2<{id:string}>('/assessments/from-past-paper','POST',{project_id:projectId,resource_id:r.id,mode},key()));
    if(result)navigate('/learning/assessments/'+result.id);
  }
  const items=query.data?.resources.filter(r=>year==null||r.year===year);
  return <><Space wrap><Select style={{width:150}} allowClear placeholder="全部年份" value={year} onChange={setYear}
    options={[...new Set(query.data?.resources.map(r=>r.year))].map(y=>({value:y,label:y+' 年'}))}/>
    <Button type="primary" disabled={!active} onClick={()=>setOpen(true)}>导入年度资料</Button>
    <Button loading={busy} disabled={!active||!query.data?.sample_available||!!query.data?.resources.some(r=>r.edition==='simulation-v1')}
      onClick={()=>void run(()=>apiV2(path+'/sample','POST',undefined,key()),'已添加模拟考纲和模拟卷')}>添加模拟资料</Button></Space>
    <p className="muted">考纲按项目目标年份管理。真题可按原卷顺序练习或限时作答。导入内容只在本项目可见。</p>
    <State query={query}>{items?.length?items.map(r=><article className="v2-note" key={r.id}>
      <Space wrap><Tag>{r.kind==='simulated_paper'?'模拟卷':r.kind==='past_paper'?'个人导入真题':
        r.edition==='simulation-v1'?'模拟考纲':'年度考纲'}</Tag><span>{r.year} 年 · {r.edition}</span></Space>
      <h3>{r.title}</h3><p>来源：{r.source.url?<a href={r.source.url} target="_blank" rel="noreferrer">{r.source.title}</a>:r.source.title} · 导入者提供</p>
      {r.kind==='syllabus'?<Collapse items={[...new Set(r.topics?.map(t=>t.chapter))].map(ch=>({key:ch,label:ch,
        children:r.topics?.filter(t=>t.chapter===ch).map(t=><div className="v2-material" key={t.code}><span>{t.title}</span>
          <Button disabled={!active} loading={busy} onClick={()=>void study(r.id,t.code)}>学习这个知识点</Button></div>)}))}/>:
        <><p>{r.question_count} 道题 · {r.minutes} 分钟 · 卷面 {r.total_points} 分</p><Space wrap>
          <Button disabled={!active} loading={busy} onClick={()=>void start(r,'practice')}>按原卷练习</Button>
          <Button disabled={!active} type="primary" onClick={()=>modal.confirm({title:'开始限时真题模考？',
            content:`开始后计时 ${r.minutes} 分钟，交卷前暂停本项目助教和原文。`,onOk:()=>start(r,'mock')})}>限时模考</Button></Space></>}
    </article>):<Blank description="这个范围暂未导入可练习的年度资料。下方可查看出版社书目。"/>}</State>
    <h3>出版社书目</h3>{query.data?.references.map(r=><p key={r.url}><a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> · {r.publisher}{r.isbn&&' · ISBN '+r.isbn}</p>)}
    <Modal title="导入考纲或历年试卷" open={open} onCancel={()=>setOpen(false)} onOk={()=>void save()} okText="导入" confirmLoading={busy} okButtonProps={{disabled:!json.trim()}}>
      <Alert type="info" message="请填写可追溯来源。有权使用该资料时，将 rights_confirmed 改为 true。样例只说明格式。"/>
      <Space wrap style={{marginBlock:12}}><Button onClick={()=>setJson(JSON.stringify({...example,year:examYear},null,2))}>填入考纲格式</Button>
        <Button onClick={()=>setJson(JSON.stringify({...paperExample,year:examYear-1},null,2))}>填入试卷格式</Button>
        <label className="v2-file-button">选择 JSON<input type="file" accept=".json" onChange={async e=>{
          const file=e.target.files?.[0];e.target.value='';
          if(file?.size&&file.size>2_000_000){message.error('JSON 文件最大 2 MB');return}
          if(file)setJson(await file.text());
        }}/></label></Space><Input.TextArea aria-label="年度资料 JSON" value={json} onChange={e=>setJson(e.target.value)} rows={12} maxLength={1000000}/>
    </Modal></>;
}
