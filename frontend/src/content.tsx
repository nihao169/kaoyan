import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Checkbox, Collapse, Form, Input, InputNumber, Modal, Radio, Select, Space, Table, Tag } from 'antd';
import { ArrowLeftOutlined, CheckOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { api, key, kindName, type Catalog, type Contracts, type QuestionInput } from './api';
import { useUser } from './App';
import { Blank, PageTitle, State, Status, useRun } from './ui';
import { DocumentPreview, IndexStatus } from './extensions';

type SourceItem = Contracts['SourceListItemOutput'];
type CardItem = Contracts['CardOutput'];
type QuestionItem = Contracts['EditorialQuestionOutput'];
type SourceDetail = Contracts['SourceOutput'];

export function ContentList() {
  const user=useUser();
  const allowed=user.roles.some(r=>['teacher','admin'].includes(r));
  const [page,setPage]=useState(1);
  const query=useQuery({queryKey:['sources',page],queryFn:()=>api<{items:SourceItem[];total:number}>('/content/sources?page='+page+'&page_size=20'),enabled:allowed});
  const catalog=useQuery({queryKey:['catalog'],queryFn:()=>api<Catalog>('/catalog'),enabled:allowed});
  const [open,setOpen]=useState(false);
  const [file,setFile]=useState<File|null>(null);
  const [importType,setImportType]=useState('text');
  const [form]=Form.useForm();
  const {run,busy}=useRun();
  const navigate=useNavigate();
  if(!allowed)return <Alert type="warning" message="需要教师或机构管理员角色才能管理教学内容。"/>;
  async function create(values:{title:string;text:string;knowledge_id:string;rights:string}) {
    await run(async()=>{
      let result:{id:string};
      if(importType==='file') {
        if(!file)throw new Error('请选择 PDF、DOCX、Markdown 或 TXT 文件');
        const body=new FormData();body.append('knowledge_id',values.knowledge_id);body.append('rights',values.rights);body.append('file',file);
        result=await api('/content/sources/upload','POST',body);
      } else result=await api('/content/sources','POST',values);
      setOpen(false);navigate('/sources/'+result.id);return result;
    },'资料已保存为草稿');
  }
  return <><PageTitle title="教学内容" description="原文、知识卡和题目按版本关联。先核对，再发布，历史引用始终可追溯。" action={<Button type="primary" icon={<PlusOutlined aria-hidden/>} onClick={()=>{form.resetFields();setFile(null);setOpen(true)}}>导入新资料</Button>}/>
    <Alert className="section-space" type="info" showIcon message="原创演示内容需要教师确认发布" description="初始资料均为草稿。请打开资料核对原文、知识卡、题目答案和评分要点，再提交审核并发布。机构管理员可编辑草稿，发布需要教师角色。"/>
    <State query={query}><Table rowKey="id" dataSource={query.data?.items??[]} pagination={{current:page,pageSize:20,total:query.data?.total??0,onChange:setPage,showSizeChanger:false}} scroll={{x:850}} columns={[
      {title:'资料名称',render:(_,r)=><Link to={'/sources/'+r.id}>{r.title}</Link>},{title:'版本',dataIndex:'number',render:n=>`V${n}`,width:80},{title:'状态',dataIndex:'status',render:v=><Status value={v}/>,width:100},{title:'使用范围',dataIndex:'visibility',render:v=>({organization:'本机构',class:'指定班级',private:'仅本人'}[v as string]??v),width:100},{title:'审核说明',dataIndex:'review_note',render:v=>v||'等待核对'},{title:'操作',render:(_,r)=><Link to={'/sources/'+r.id}><Button>核对与管理</Button></Link>,width:130},
    ]}/></State>
    <Modal title="导入教学资料" open={open} onCancel={()=>setOpen(false)} footer={null} width={680}><Form form={form} layout="vertical" onFinish={create} initialValues={{rights:'原创资料，允许在本机构教学中使用'}} requiredMark={false}>
      <Radio.Group className="section-space" value={importType} onChange={e=>setImportType(e.target.value)} options={[{value:'text',label:'输入正文'},{value:'file',label:'上传文件'}]}/>
      {importType==='text'?<><Form.Item name="title" label="资料名称" rules={[{required:true}]}><Input maxLength={200}/></Form.Item><Form.Item name="text" label="原文正文" rules={[{required:true}]}><Input.TextArea rows={8} maxLength={500000} placeholder="可使用 Markdown 标题组织章节；发布前请核对正文。"/></Form.Item></>:<div className="upload-field"><label htmlFor="source-file">选择 PDF / DOCX / Markdown / TXT（文本文件 UTF-8，最大 5 MB）</label><input id="source-file" type="file" accept=".pdf,.docx,.md,.txt" onChange={e=>setFile(e.target.files?.[0]??null)}/></div>}
      <Form.Item name="knowledge_id" label="对应知识点" rules={[{required:true}]}><Select options={catalog.data?.knowledge.map(k=>({value:k.id,label:k.name}))}/></Form.Item><Form.Item name="rights" label="来源与使用授权说明" rules={[{required:true}]}><Input.TextArea rows={2} maxLength={2000}/></Form.Item><Button htmlType="submit" type="primary" loading={busy} icon={<UploadOutlined aria-hidden/>}>保存为草稿</Button>
    </Form></Modal>
  </>;
}

export function SourceView() {
  const {versionId}=useParams();
  return <SourcePage key={versionId} versionId={versionId!}/>;
}

function SourcePage({versionId}:{versionId:string}) {
  const user=useUser();
  const editor=user.roles.some(r=>['teacher','admin'].includes(r));
  const teacher=user.roles.includes('teacher');
  const navigate=useNavigate();
  const query=useQuery({queryKey:['source',versionId],queryFn:()=>api<SourceDetail>('/sources/versions/'+versionId)});
  const index=useQuery({queryKey:['index',versionId],queryFn:()=>api<{state:string}>('/content/indexes/'+versionId),enabled:editor,refetchInterval:q=>q.state.data?.state==='ready'?false:2000});
  const [text,setText]=useState('');
  const [action,setAction]=useState<string|null>(null);
  const [note,setNote]=useState('');
  const [cardEditor,setCardEditor]=useState<CardItem|'new'|null>(null);
  const [questionEditor,setQuestionEditor]=useState<QuestionItem|'new'|null>(null);
  const [cardForm]=Form.useForm();
  const {run,busy}=useRun();
  const source=query.data;
  useEffect(()=>{if(source)setText(source.text)},[source?.text]);
  useEffect(()=>{if(cardEditor){cardForm.setFieldsValue(cardEditor==='new'?{title:'',body:''}:cardEditor)}},[cardEditor,cardForm]);
  const writable=editor&&source?.status==='draft';
  async function transition(){
    if(!note.trim())return;
    await run(async()=>{const result=await api('/content/sources/'+versionId+'/'+action,'POST',{note},key());setAction(null);setNote('');return result},'内容状态已更新');
  }
  return <><PageTitle title={source?.title??'资料原文'} description="定位到真实原文与具体版本。所有内容由系统保存，不使用模型生成的虚构出处。" action={<Link to={editor?'/content':'/mistakes'}><Button icon={<ArrowLeftOutlined aria-hidden/>}>返回{editor?'内容列表':'补学'}</Button></Link>}/><State query={query}>{source&&<>
    {editor&&<IndexStatus versionId={versionId}/>}<DocumentPreview versionId={versionId} teacher={teacher&&source.status==='draft'}/><div className="source-toolbar"><Space wrap><Status value={source.status}/><Tag>版本 {source.number}</Tag><Tag>{source.rights}</Tag></Space>{editor&&<Space wrap>
      {writable&&teacher&&<Button disabled={index.data?.state!=='ready'} type="primary" onClick={()=>{setAction('submit');setNote('')}}>提交审核</Button>}
      {source.status==='pending'&&teacher&&<Button disabled={index.data?.state!=='ready'} type="primary" icon={<CheckOutlined aria-hidden/>} onClick={()=>{setAction('publish');setNote('')}}>审核确认并发布</Button>}
      {source.status==='pending'&&teacher&&<Button onClick={()=>{setAction('reject');setNote('')}}>退回草稿</Button>}
      {source.status==='published'&&teacher&&<Button danger onClick={()=>{setAction('withdraw');setNote('')}}>撤回发布</Button>}
      {['published','withdrawn'].includes(source.status)&&teacher&&<Button loading={busy} onClick={()=>run(async()=>{const result=await api<{id:string}>('/content/sources/'+source.id+'/versions','POST');navigate('/sources/'+result.id);return result},'已创建新版本草稿')}>创建修订版本</Button>}
    </Space>}</div>
    {source.status==='withdrawn'&&<Alert className="section-space" type="warning" showIcon message="此内容已撤回，不再用于新的学习与检索" description={source.review_note}/>}
    {source.review_note&&source.status!=='withdrawn'&&<div className="review-note">审核记录：{source.review_note}</div>}
    <div className={editor?'source-columns':'source-reader'}><section className="panel source-text"><div className="section-heading"><h2>资料原文</h2>{writable&&!source.document_info&&<Button loading={busy} disabled={text===source.text} onClick={()=>run(()=>api('/content/sources/'+source.id,'PATCH',{text,revision:source.revision}),'正文已保存')}>保存正文</Button>}</div>
      {writable&&!source.document_info?<Input.TextArea aria-label="资料原文正文" rows={22} value={text} onChange={e=>setText(e.target.value)} maxLength={500000}/>:<div className="article-text">{source.text.split(/\n\s*\n/).map((p,i)=>p.startsWith('#')?<h3 key={i}>{p.replace(/^#+\s*/,'')}</h3>:<p key={i}>{p}</p>)}</div>}
      <div className="small-note">章节与段落定位，不提供虚构页码。正文摘要用于版本核对。</div>
      <Collapse items={[{key:'locations',label:'查看原文段落位置',children:source.chunks.map(c=><div className="source-chunk" key={c.id} id={c.id}><Tag>第 {c.position} 段</Tag><strong>{c.heading}</strong><p>{c.text}</p></div>)}]}/>
    </section><section><div className="panel"><div className="section-heading"><h2>关联知识卡</h2>{writable&&<Button icon={<PlusOutlined aria-hidden/>} onClick={()=>setCardEditor('new')}>添加知识卡</Button>}</div>{!source.cards.length?<Blank description="尚未添加知识卡"/>:source.cards.map(card=><div className="content-card" key={card.id}><div className="section-heading"><h3>{card.title}</h3>{writable&&<Button type="link" onClick={()=>setCardEditor(card)}>编辑</Button>}</div><p>{card.body}</p><Status value={card.status}/>{teacher&&writable&&<Select aria-label="知识卡适用错因" mode="multiple" style={{width:'100%',marginTop:12}} placeholder="选择此卡适用的错因" value={card.causes??[]} options={['概念混淆','原理适用','材料理解','论证表达','审题','时间管理'].map(c=>({value:c,label:c}))} onChange={causes=>run(()=>api('/content/cards/'+card.id+'/causes','PUT',{causes}),'知识卡错因关联已保存')}/>}</div>)}</div>
      {editor&&<div className="panel section-space"><div className="section-heading"><h2>关联题目与评分</h2>{writable&&<Button icon={<PlusOutlined aria-hidden/>} onClick={()=>setQuestionEditor('new')}>添加题目</Button>}</div>{!source.questions?.length?<Blank description="尚未添加题目"/>:<Collapse items={source.questions.map(q=>({key:q.id,label:<span>{kindName(q.kind)} · {q.prompt}</span>,children:<><p>{q.explanation}</p>{Object.entries(q.options??{}).map(([k,v])=><p key={k}>{k}. {v}</p>)}{!!q.answer?.length&&<p><strong>审核答案：{q.answer.join('、')}</strong></p>}{q.rubric?.map((r,i)=><p key={i}>{String(r.label)}：{String(r.score)} 分</p>)}<p>提示已设 {q.hints.length} 级 · 满分 {q.max_score}</p>{writable&&<Button onClick={()=>setQuestionEditor(q)}>编辑题目</Button>}</>}))}/>}</div>}
    </section></div>
    {!!source.affected_attempts?.length&&<section className="panel section-space"><div className="section-heading"><div><h2>使用此版本的学习记录</h2><p>内容修订或撤回后，可据此定位需要教师复核的作答；不会自动改写成绩。</p></div></div><Table rowKey="id" dataSource={source.affected_attempts} pagination={{pageSize:5}} columns={[{title:'学生',dataIndex:'student'},{title:'作答状态',dataIndex:'status',render:v=><Status value={v}/>},{title:'查看证据',render:(_,r)=><Link to={'/teacher/attempts/'+r.id}>打开作答与评价</Link>}]}/></section>}
    <Modal title={action==='publish'?'核对并发布教学内容':action==='submit'?'提交内容审核':action==='reject'?'退回草稿':'撤回教学内容'} open={!!action} onCancel={()=>setAction(null)} onOk={transition} confirmLoading={busy} okButtonProps={{disabled:!note.trim()}} okText={action==='publish'?'确认发布':action==='submit'?'提交审核':action==='reject'?'确认退回':'确认撤回'}><p>{action==='publish'?'请确认已核对正文、知识卡、选项答案、提示和评分要点，且拥有相应教学使用权限。发布后该版本冻结，学生可以检索和使用。':action==='submit'?'提交后不能直接编辑，审核通过后进入学习与检索。':action==='reject'?'填写需要修改的内容，退回后可以重新编辑正文、知识卡和题目。':'撤回后不再分配给新任务，历史作答继续保留引用及撤回说明。'}</p><Input.TextArea aria-label="审核说明" rows={4} value={note} onChange={e=>setNote(e.target.value)} placeholder="填写审核意见或撤回原因" maxLength={2000}/></Modal>
    <Modal title={cardEditor==='new'?'添加知识卡':'编辑知识卡'} open={!!cardEditor} onCancel={()=>setCardEditor(null)} footer={null}><Form form={cardForm} layout="vertical" onFinish={values=>run(async()=>{const result=await api(cardEditor==='new'?'/content/cards':'/content/cards/'+(cardEditor as CardItem).id,cardEditor==='new'?'POST':'PUT',{...values,source_version_id:source.id});setCardEditor(null);return result},'知识卡已保存')}><Form.Item name="title" label="卡片标题" rules={[{required:true}]}><Input maxLength={200}/></Form.Item><Form.Item name="body" label="知识卡内容" rules={[{required:true}]}><Input.TextArea rows={6} maxLength={20000}/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>保存知识卡</Button></Form></Modal>
    {questionEditor&&<QuestionEditor versionId={source.id} question={questionEditor} close={()=>setQuestionEditor(null)}/>}
  </>}</State></>;
}

type QuestionForm={kind:'single'|'multiple'|'essay';prompt:string;optionA:string;optionB:string;optionC:string;optionD:string;answer:string[];explanation:string;hints:string[];rubric:{label:string;score:number}[];max_score:number};
function QuestionEditor({versionId,question,close}:{versionId:string;question:QuestionItem|'new';close:()=>void}) {
  const [form]=Form.useForm<QuestionForm>();
  const kind=Form.useWatch('kind',form)??'single';
  const {run,busy}=useRun();
  useEffect(()=>{
    if(question==='new') form.setFieldsValue({kind:'single',prompt:'',optionA:'',optionB:'',optionC:'',optionD:'',answer:[],explanation:'',hints:['','','',''],rubric:[{label:'原理阐述',score:4},{label:'材料分析',score:6}],max_score:2});
    else form.setFieldsValue({...question,optionA:question.options?.A??'',optionB:question.options?.B??'',optionC:question.options?.C??'',optionD:question.options?.D??'',rubric:(question.rubric??[]) as {label:string;score:number}[]});
  },[question,form]);
  async function save(values:QuestionForm) {
    const body:QuestionInput={source_version_id:versionId,kind:values.kind,prompt:values.prompt,
      options:values.kind==='essay'?{}:Object.fromEntries(['A','B','C','D'].map(k=>[k,values[('option'+k) as keyof QuestionForm]]).filter(([,v])=>!!v)) as Record<string,string>,
      answer:values.kind==='essay'?[]:values.answer,explanation:values.explanation,hints:values.hints,
      rubric:values.kind==='essay'?values.rubric:[],max_score:values.max_score};
    await run(async()=>{const result=await api(question==='new'?'/content/questions':'/content/questions/'+question.id,question==='new'?'POST':'PUT',body);close();return result},'题目已保存');
  }
  return <Modal title={question==='new'?'添加审核题目':'编辑题目与评分要点'} open onCancel={close} footer={null} width={780}><Form form={form} layout="vertical" onFinish={save} requiredMark={false}>
    <div className="form-inline"><Form.Item name="kind" label="题型" rules={[{required:true}]}><Select disabled={question!=='new'} options={[{value:'single',label:'单选题'},{value:'multiple',label:'多选题'},{value:'essay',label:'分析题'}]} onChange={value=>form.setFieldsValue({answer:[],max_score:value==='essay'?10:value==='multiple'?4:2})}/></Form.Item><Form.Item name="max_score" label="满分" rules={[{required:true}]}><InputNumber min={1} max={100} precision={0}/></Form.Item></div>
    <Form.Item name="prompt" label="题干或材料" rules={[{required:true}]}><Input.TextArea rows={3} maxLength={10000}/></Form.Item>
    {kind!=='essay'?<><div className="form-inline">{['A','B','C','D'].map(k=><Form.Item key={k} name={'option'+k} label={'选项 '+k} rules={['A','B'].includes(k)?[{required:true}]:[]}><Input/></Form.Item>)}</div><Form.Item name="answer" label={kind==='single'?'审核答案（仅选一项）':'审核答案（至少两项）'} rules={[{required:true}]}><Checkbox.Group options={['A','B','C','D']}/></Form.Item></>:<Form.List name="rubric">{(fields,{add,remove})=><><h3>评分要点</h3>{fields.map(field=><Space key={field.key} align="baseline"><Form.Item name={[field.name,'label']} rules={[{required:true,message:'填写要点'}]}><Input placeholder="评分要点"/></Form.Item><Form.Item name={[field.name,'score']} rules={[{required:true,message:'填写分值'}]}><InputNumber min={1} max={100} precision={0} placeholder="分值"/></Form.Item><Button onClick={()=>remove(field.name)} danger type="text">移除</Button></Space>)}<Button onClick={()=>add({label:'',score:1})}>添加评分要点</Button><p className="small-note">分项满分之和须等于题目满分。</p></>}</Form.List>}
    <Form.Item name="explanation" label="审核解析" rules={[{required:true}]}><Input.TextArea rows={3}/></Form.Item>
    <h3>递进提示</h3>{['相关概念','突破口','分步引导','完整解析'].map((label,i)=><Form.Item key={label} name={['hints',i]} label={`${i+1}. ${label}`} rules={[{required:true}]}><Input.TextArea rows={2}/></Form.Item>)}
    <Button type="primary" htmlType="submit" loading={busy}>保存题目</Button>
  </Form></Modal>;
}
