import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Checkbox, Collapse, Input, InputNumber, Modal, Select, Space, Tag } from 'antd';
import { apiV2, key } from './api';
import { State, useRun } from './ui';

export type AnnualKind = 'syllabus'|'past_paper';
type Topic = {code?:string;chapter?:string;title?:string;text?:string};
type Question = {number:number;kind?:'single'|'multiple'|'essay';knowledge?:string;prompt?:string;
  options?:Record<string,string>;answer?:string[];rubric?:string[];explanation?:string;points?:number};
type Resource = {kind:AnnualKind;year?:number;title?:string;source_title?:string;source_url?:string;
  edition?:string;minutes?:number;rights_confirmed:boolean;topics?:Topic[];questions?:Question[]};
type Draft = {id:string;state:string;kind:AnnualKind;error:string;files:{name:string}[];resource_id?:string;edition:string;
  revision:number;text?:string;draft?:Resource;issues?:string[]};
const processing = (draft:Draft) => ['queued','running'].includes(draft.state);
const kindName = (kind:AnnualKind) => kind==='syllabus'?'考纲':'历年真题';

export function AnnualDrafts({projectId,examYear,active,requested,closeRequested,onImported}:{
  projectId:string;examYear:number;active:boolean;requested?:AnnualKind;closeRequested:()=>void;onImported:()=>void;
}) {
  const path='/learning-projects/'+projectId+'/annual-drafts';
  const [kind,setKind]=useState<AnnualKind>();
  const [selected,setSelected]=useState<string>();
  const list=useQuery({queryKey:['annual-drafts',projectId],queryFn:()=>apiV2<Draft[]>(path),
    refetchInterval:q=>q.state.data?.some(processing)?2000:false});
  const item=useQuery({queryKey:['annual-draft',projectId,selected],queryFn:()=>apiV2<Draft>(path+'/'+selected),
    enabled:!!selected,refetchInterval:q=>q.state.data&&processing(q.state.data)?2000:false});
  function closeUpload() {setKind(undefined);closeRequested();}
  return <section className="panel section-space">
    <h3>从文件导入并核对</h3>
    <Space wrap>
      <Button disabled={!active} onClick={()=>setKind('syllabus')}>上传考纲文件</Button>
      <Button disabled={!active} onClick={()=>setKind('past_paper')}>上传历年真题文件</Button>
    </Space>
    <State query={list}>{list.data?.map(draft=><div className="v2-material" key={draft.id}>
      <div><strong>{draft.files[0]?.name}</strong> <Tag>{draft.resource_id?'已入库':processing(draft)?'正在提取':draft.state==='failed'?'提取未完成':'待核对'}</Tag></div>
      <Button onClick={()=>setSelected(draft.id)}>{draft.resource_id?'查看原件':'查看草稿'}</Button>
    </div>)}</State>
    {(requested||kind)&&<UploadDialog path={path} kind={(requested||kind)!} onClose={closeUpload} onUploaded={id=>{closeUpload();setSelected(id)}}/>}
    {selected&&<Modal open title="核对年度资料" width={1100} footer={null} onCancel={()=>setSelected(undefined)} destroyOnHidden>
      <State query={item}>{item.data&&<DraftEditor key={item.data.id} draft={item.data} path={path+'/'+selected}
        examYear={examYear} active={active} onImported={()=>{setSelected(undefined);onImported()}}/>}</State>
    </Modal>}
  </section>;
}

function UploadDialog({path,kind,onClose,onUploaded}:{path:string;kind:AnnualKind;onClose:()=>void;onUploaded:(id:string)=>void}) {
  const {busy,run}=useRun();
  const [file,setFile]=useState<File>();
  const [answer,setAnswer]=useState<File>();
  async function upload() {
    if(!file)return;
    const body=new FormData();
    body.set('kind',kind);
    body.set('file',file);
    if(answer)body.set('answer',answer);
    const result=await run(()=>apiV2<Draft>(path,'POST',body),'原件已保存，正在提取');
    if(result)onUploaded(result.id);
  }
  return <Modal open title={'上传'+kindName(kind)} onCancel={onClose} onOk={()=>void upload()}
    okText="上传并提取" confirmLoading={busy} okButtonProps={{disabled:!file}}>
    <p>支持文字型 PDF、DOCX、TXT、Markdown。扫描件请先 OCR。</p>
    <label className="annual-file">{kindName(kind)}正文 <input type="file" accept=".pdf,.docx,.txt,.md"
      onChange={e=>setFile(e.target.files?.[0])}/></label>
    {kind==='past_paper'&&<label className="annual-file">独立答案文件（可选） <input type="file" accept=".pdf,.docx,.txt,.md"
      onChange={e=>setAnswer(e.target.files?.[0])}/></label>}
  </Modal>;
}

function DraftEditor({draft,path,examYear,active,onImported}:{draft:Draft;path:string;examYear:number;active:boolean;onImported:()=>void}) {
  return <div className="annual-review">
    <section><h3>原文</h3><Space wrap>{draft.files.map((file,i)=><a href={'/api/v2'+path+'/files/'+i} key={i} download>{file.name}</a>)}</Space>
      <pre>{draft.text}</pre></section>
    <section><h3>提取草稿</h3>
      {processing(draft)?<Alert type="info" showIcon message="正在提取，关闭窗口后可从年度资料继续查看。"/>:
        draft.resource_id?<Alert type="success" showIcon message="已核对并导入本项目"/>:
        active&&<ResourceForm key={draft.state} draft={draft} path={path} examYear={examYear} onImported={onImported}/>}
    </section>
  </div>;
}

function ResourceForm({draft,path,examYear,onImported}:{draft:Draft;path:string;examYear:number;onImported:()=>void}) {
  const {busy,run}=useRun();
  const [resource,setResource]=useState<Resource>(draft.draft?{
    ...draft.draft,
    edition:draft.revision===0&&draft.draft.edition==='v1'?draft.edition:draft.draft.edition,
  }:{
    kind:draft.kind,year:draft.kind==='syllabus'?examYear:undefined,title:draft.files[0]?.name,
    source_title:draft.files[0]?.name,edition:draft.edition,rights_confirmed:false,topics:[],questions:[],
  });
  const [revision,setRevision]=useState(draft.revision);
  const patch=(fields:Partial<Resource>)=>setResource(previous=>({...previous,...fields}));
  const topics=resource.topics??[];
  const questions=resource.questions??[];
  async function save(importing:boolean) {
    const saved=await run(()=>apiV2<Draft>(path,'PUT',{resource,revision}),importing?undefined:'草稿已保存');
    if(!saved)return;
    setRevision(saved.revision);
    if(importing&&await run(()=>apiV2(path+'/confirm','POST',undefined,key()),'已导入年度资料'))onImported();
  }
  return <div className="annual-fields">
    {draft.error&&<Alert type="warning" showIcon message={draft.error}
      action={<Button loading={busy} onClick={()=>run(()=>apiV2(path+'/retry','POST'))}>恢复提取</Button>}/>}
    {!!draft.issues?.length&&<Alert type="warning" showIcon message="需要对照原文核对"
      description={<ul>{draft.issues.map(issue=><li key={issue}>{issue}</li>)}</ul>}/>}
    <label>标题 <Input value={resource.title} onChange={e=>patch({title:e.target.value})} status={!resource.title?'error':undefined}/></label>
    <label>版本 <Input value={resource.edition} onChange={e=>patch({edition:e.target.value})} status={!resource.edition?'error':undefined}/></label>
    <label>年份 <InputNumber value={resource.year} min={1980} max={2100} onChange={value=>patch({year:value??undefined})}
      status={!resource.year?'error':undefined}/></label>
    <label>来源名称 <Input value={resource.source_title} onChange={e=>patch({source_title:e.target.value})}
      status={!resource.source_title?'error':undefined}/></label>
    <label>来源链接（可选） <Input value={resource.source_url} onChange={e=>patch({source_url:e.target.value||undefined})}/></label>
    {draft.kind==='past_paper'&&<label>考试时长（分钟） <InputNumber min={5} max={180} value={resource.minutes}
      status={!resource.minutes?'error':undefined} onChange={value=>patch({minutes:value??undefined})}/></label>}
    {draft.kind==='syllabus'?<>
      <Collapse items={topics.map((topic,i)=>({key:String(i),label:topic.title||'待补主题 '+(i+1),
        children:<div className="annual-fields">
          <label>章节 <Input value={topic.chapter} status={!topic.chapter?'error':undefined}
            onChange={e=>patch({topics:topics.map((row,n)=>i===n?{...row,chapter:e.target.value}:row)})}/></label>
          <label>主题 <Input value={topic.title} status={!topic.title?'error':undefined}
            onChange={e=>patch({topics:topics.map((row,n)=>i===n?{...row,title:e.target.value}:row)})}/></label>
          <label>对应原文 <Input.TextArea rows={4} value={topic.text} status={!topic.text?'error':undefined}
            onChange={e=>patch({topics:topics.map((row,n)=>i===n?{...row,text:e.target.value}:row)})}/></label>
          <Button danger onClick={()=>patch({topics:topics.filter((_,n)=>n!==i)})}>移除此主题</Button>
        </div>}))}/>
      <Button disabled={topics.length>=500} onClick={()=>patch({topics:[...topics,{code:'manual-'+key()}]})}>补录主题</Button>
    </>:<>
      <Collapse items={questions.map((question,i)=>({key:String(i),
        label:'第 '+question.number+' 题 · '+(question.prompt?.slice(0,45)||'待补题干'),
        children:<QuestionEditor question={question} patch={fields=>patch({questions:questions.map((row,n)=>i===n?{...row,...fields}:row)})}
          remove={()=>patch({questions:questions.filter((_,n)=>n!==i)})}/>}))}/>
      <Button disabled={questions.length>=50} onClick={()=>patch({questions:[...questions,{number:Math.max(0,...questions.map(q=>q.number))+1}]})}>补录试题</Button>
    </>}
    <Checkbox checked={resource.rights_confirmed} onChange={e=>patch({rights_confirmed:e.target.checked})}>已核对原文与结构化字段，并确认有权使用此资料</Checkbox>
    <Space wrap><Button loading={busy} onClick={()=>save(false)}>保存草稿</Button>
      <Button type="primary" loading={busy} disabled={!resource.rights_confirmed||(draft.kind==='past_paper'&&!resource.minutes)}
        onClick={()=>save(true)}>确认并导入</Button></Space>
  </div>;
}

function QuestionEditor({question:q,patch,remove}:{question:Question;patch:(fields:Partial<Question>)=>void;remove:()=>void}) {
  const [options,setOptions]=useState(Object.entries(q.options??{}).map(([k,v])=>k+'. '+v).join('\n'));
  return <div className="annual-fields">
    <label>题号 <InputNumber min={1} max={50} value={q.number} onChange={value=>value&&patch({number:value})}/></label>
    <label>题型 <Select style={{minWidth:120}} value={q.kind} status={!q.kind?'error':undefined}
      options={[{value:'single',label:'单选'},{value:'multiple',label:'多选'},{value:'essay',label:'分析题'}]}
      onChange={kind=>patch({kind,answer:[],rubric:[],options:kind==='essay'?{}:q.options})}/></label>
    <label>分值 <InputNumber min={1} max={100} value={q.points} status={!q.points?'error':undefined}
      onChange={value=>patch({points:value??undefined})}/></label>
    <label>考点 <Input value={q.knowledge} onChange={e=>patch({knowledge:e.target.value})} status={!q.knowledge?'error':undefined}/></label>
    <label>题干 <Input.TextArea value={q.prompt} onChange={e=>patch({prompt:e.target.value})} status={!q.prompt?'error':undefined}/></label>
    {q.kind==='essay'?<label>评分要点（每行一项） <Input.TextArea defaultValue={q.rubric?.join('\n')} status={!q.rubric?.length?'error':undefined}
      onChange={e=>patch({rubric:e.target.value.split('\n').map(s=>s.trim()).filter(Boolean)})}/></label>:<>
      <label>选项（每行一项，如 A. 选项内容） <Input.TextArea value={options} status={!q.options||Object.keys(q.options).length<2?'error':undefined}
        onChange={e=>{setOptions(e.target.value);patch({options:Object.fromEntries(e.target.value.split('\n').flatMap(line=>{
          const match=line.match(/^([A-Za-z])[.．、:]\s*(.+)$/);
          return match?[[match[1].toUpperCase(),match[2]]]:[];
        }))})}}/></label>
      <label>正确选项 <Select mode="multiple" style={{minWidth:120}} value={q.answer} status={!q.answer?.length?'error':undefined}
        options={Object.keys(q.options??{}).map(value=>({value,label:value}))} onChange={answer=>patch({answer})}/></label>
    </>}
    <label>答案解析 <Input.TextArea value={q.explanation} onChange={e=>patch({explanation:e.target.value})} status={!q.explanation?'error':undefined}/></label>
    <Button danger onClick={remove}>移除此题</Button>
  </div>;
}
