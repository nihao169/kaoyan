import { useState } from 'react';
import { Alert, App, Button, Empty, Spin, Tag } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError, stateName, type Evidence } from './api';

export function useRun() {
  const [busy, setBusy] = useState(false);
  const { message } = App.useApp();
  const client = useQueryClient();
  async function run<T>(fn: () => Promise<T>, success?: string): Promise<T | undefined> {
    setBusy(true);
    try {
      const result = await fn();
      if (success) message.success({content:success,key:'action-feedback',duration:2});
      await client.invalidateQueries({predicate:q=>q.queryKey[0]!=='me'});
      return result;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败，请重试');
      return undefined;
    } finally { setBusy(false); }
  }
  return { busy, run };
}

export function PageTitle({title,description,action}:{title:string;description:string;action?:React.ReactNode}) {
  return <div className="page-title"><div><div className="eyebrow">知行研学 / LEARNING WORKSPACE</div><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

export function State({query,children}:{query:{isPending:boolean;error:Error|null;refetch:()=>unknown};children:React.ReactNode}) {
  if (query.isPending) return <div className="loading"><Spin tip="正在读取已保存的记录"><div/></Spin></div>;
  if (query.error) return <Alert type="error" showIcon message={query.error.message} description={query.error instanceof ApiError && query.error.status===401 ? '登录已失效，请刷新页面重新登录。' : '暂时无法读取记录。服务恢复后，点击重试即可继续。'} action={<Button onClick={()=>query.refetch()}>重试</Button>}/>;
  return <>{children}</>;
}

export function Status({value}:{value:string}) {
  const color = ['published','graded','completed','resolved'].includes(value)?'green':['pending','pending_teacher','open','needs_remediation'].includes(value)?'gold':value==='withdrawn'?'red':'default';
  return <Tag color={color}>{stateName(value)}</Tag>;
}

export function Blank({description,children}:{description:string;children?:React.ReactNode}) {
  return <div className="blank"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description}>{children}</Empty></div>;
}

export function Sources({items}:{items:Evidence[]}) {
  if (!items.length) return <Alert type="info" message="没有找到可用的审核依据，请联系教师补充资料。"/>;
  return <div className="evidence-list">{items.map(item=><div className="evidence" key={item.chunk_id}>
    <div className="evidence-meta">原文依据 · 版本 {item.version} · 第 {item.position} 段</div>
    <Link to={item.url}>{item.source_title} / {item.heading}</Link><p>{item.text}</p>
  </div>)}</div>;
}

export const date = (value:string) => new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
