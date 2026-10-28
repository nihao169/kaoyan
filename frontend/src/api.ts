import type { components } from './generated/api';
export type Contracts = components['schemas'];
export type GoalInput = components['schemas']['GoalInput'];
export type DraftInput = components['schemas']['DraftInput'];
export type QuestionInput = components['schemas']['QuestionInput'];
export type User = components['schemas']['MeOutput'];
export type Evaluation = components['schemas']['EvaluationOutput'];
export type Question = components['schemas']['QuestionOutput'];
export type Evidence = components['schemas']['EvidenceOutput'];
export type Task = components['schemas']['TaskOutput'];
export type Attempt = Omit<components['schemas']['AttemptOutput'],'revisions'|'events'> & {revisions?: {number:number;score:number;feedback:string;method:string}[]; events?: {kind:string;payload:Record<string,unknown>;created_at:string}[]};
export type Catalog = components['schemas']['CatalogOutput'];
export class ApiError extends Error { constructor(public code:string, message:string, public status:number) {super(message)} }
let csrf = '';
export function setCsrf(value:string) { csrf = value; }
export async function api<T>(path: string, method='GET', body?: unknown, key?:string): Promise<T> {
  const headers: Record<string,string> = {};
  if (body && !(body instanceof FormData)) headers['Content-Type']='application/json';
  if (method!=='GET') headers['X-CSRF-Token']=csrf;
  if (key) headers['Idempotency-Key']=key;
  const response = await fetch('/api/v1'+path, {method,credentials:'same-origin',headers,
    body: body instanceof FormData ? body : body===undefined ? undefined : JSON.stringify(body)});
  const payload = await response.json();
  if (!response.ok) throw new ApiError(payload.error?.code??'REQUEST_FAILED', payload.error?.message??'请求失败',response.status);
  return payload.data as T;
}
export const key = () => crypto.randomUUID();
export const kindName = (kind:string) => ({single:'单选题',multiple:'多选题',essay:'分析题'}[kind]??kind);
export const stateName = (state:string) => ({draft:'草稿',pending:'待审核',published:'已发布',withdrawn:'已撤回',todo:'待学习',completed:'已完成',pending_teacher:'待教师评分',graded:'已评分',scheduled:'已安排',cancelled:'已取消',needs_remediation:'需补学',open:'待复核',resolved:'已处理'}[state]??state);
