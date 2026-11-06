import { createContext, useContext, useLayoutEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { App as AntApp, Avatar, Button, Form, Input, Tag, Tooltip } from 'antd';
import { BookOutlined, CalendarOutlined, CheckSquareOutlined, EditOutlined, FileTextOutlined, HomeOutlined, LogoutOutlined, MenuOutlined, ReadOutlined, TeamOutlined, UserOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { api, apiV2, setCsrf, type User } from './api';
import { State } from './ui';
import { Goals, Study, Reviews, History } from './student';
import { Teacher, TeacherAttempt, Cases, AdminUsers } from './teacher';
import { ContentList, SourceView } from './content';
import { AISettings, KnowledgeStatus, Referrals, Lessons } from './extensions';
import { StudentAssignments, TeacherAssignments, AssignmentWork, MistakeDiagnoses } from './workflows';
import { TodayV2, ProjectsV2, ProjectV2, StudyV2, LibraryV2, ReportsV2 } from './v2';
import { AssessmentsV2, AssessmentV2 } from './v2-assessments';
import { MasteryReview } from './mastery-reviews';

const Auth = createContext<User | null>(null);
export function useUser() { return useContext(Auth)!; }

function Login() {
  const [busy,setBusy] = useState(false);
  const [registering,setRegistering] = useState(false);
  const {message} = AntApp.useApp();
  const client = useQueryClient();
  const navigate = useNavigate();
  async function login(values:{username:string;password:string;name?:string}) {
    setBusy(true);
    try {
      if(registering) await apiV2('/auth/register','POST',{...values,username:values.username.trim()});
      else await api('/auth/login','POST',{username:values.username.trim(),password:values.password});
      const user = await api<User>('/me');
      await client.cancelQueries({queryKey:['me'],exact:true});
      setCsrf(user.csrf_token);
      client.removeQueries({predicate:q=>q.queryKey[0]!=='me'});
      client.setQueryData(['me'],user);
      navigate('/',{replace:true});
    } catch(e) { message.error(e instanceof Error?e.message:'登录失败'); }
    finally {setBusy(false)}
  }
  return <div className="login-page"><div className="login-story">
    <div className="brand"><span className="brand-mark"><ReadOutlined aria-hidden/></span><span>知行研学<small>ZHIXING LEARNING</small></span></div>
    <div className="login-copy"><div className="eyebrow">让每一次学习，都有迹可循</div><h1>从理解开始，<br/>让知识成为能力。</h1><p>目标、练习、反馈与复习，连接成一条属于你的学习路径。把每一次疑问，变成下一步的方向。</p>
    <div className="learning-path"><span>独立思考</span><ArrowRightOutlined aria-hidden/><span>有据补学</span><ArrowRightOutlined aria-hidden/><span>再次验证</span></div></div>
    <div className="login-note"><BookOutlined aria-hidden/> 考研政治 · 原创示例课程</div>
  </div><div className="login-form"><div className="login-box"><Tag color="green">学习工作台</Tag><h2>{registering?'开始自主学习':'欢迎回来'}</h2><p className="muted">{registering?'创建个人空间，无需先加入教师班级。':'登录后继续你的学习与教学工作。'}</p>
    <Form layout="vertical" onFinish={login} initialValues={{username:'student'}} requiredMark={false}>
      <Form.Item name="username" label="账号" rules={[{required:true,message:'请输入账号'},...(registering?[{pattern:/^\s*[A-Za-z0-9_-]{3,60}\s*$/,message:'账号须为 3 至 60 个字母、数字、下划线或连字符'}]:[])]}><Input size="large" prefix={<UserOutlined aria-hidden/>} autoComplete="username"/></Form.Item>
      {registering&&<Form.Item key="register-name" name="name" label="称呼" rules={[{required:true,whitespace:true,message:'请输入称呼'}]}><Input size="large" maxLength={80}/></Form.Item>}
      <Form.Item key="auth-password" name="password" label="密码" rules={[{required:true,message:'请输入密码'},...(registering?[{min:10,max:128,message:'密码须为 10 至 128 个字符'}]:[])]}><Input.Password size="large" autoComplete={registering?'new-password':'current-password'} placeholder={registering?'至少 10 个字符':'请输入密码'}/></Form.Item>
      <Button type="primary" block size="large" htmlType="submit" loading={busy}>{registering?'创建个人学习空间':'进入工作台'} <ArrowRightOutlined aria-hidden/></Button>
    </Form>
    <Button type="link" onClick={()=>setRegistering(!registering)}>{registering?'已有账号，返回登录':'没有账号？开始自主学习'}</Button>
  </div></div></div>;
}

function Role({role,children}:{role:string;children:React.ReactNode}) {
  return useUser().roles.includes(role)?<>{children}</>:<Navigate to="/" replace/>;
}

function ScrollToTop() {
  const {pathname}=useLocation();
  const {message}=AntApp.useApp();
  useLayoutEffect(()=>{window.scrollTo(0,0);message.destroy('action-feedback')},[pathname,message]);
  return null;
}

function Shell({user}:{user:User}) {
  const [menu,setMenu] = useState(false);
  const client = useQueryClient();
  const {message}=AntApp.useApp();
  const links = user.roles.includes('student') ? [
    ['/',<HomeOutlined aria-hidden/>,'今日学习'],['/learning/projects',<BookOutlined aria-hidden/>,'学习项目'],['/learning/assessments',<EditOutlined aria-hidden/>,'练习与模考'],['/learning/library',<ReadOutlined aria-hidden/>,'资料与笔记'],['/learning/reports',<FileTextOutlined aria-hidden/>,'学习报告'],['/assignments',<CheckSquareOutlined aria-hidden/>,'教师作业'],['/mistakes',<EditOutlined aria-hidden/>,'错题诊断'],['/reviews',<CalendarOutlined aria-hidden/>,'历史复习'],['/help',<TeamOutlined aria-hidden/>,'教师帮助'],
  ] : [
    ...(user.roles.includes('teacher')? [['/',<HomeOutlined aria-hidden/>,'教学概览'],['/assignments',<CheckSquareOutlined aria-hidden/>,'作业与批阅'],['/teacher',<TeamOutlined aria-hidden/>,'班级与作答'],['/cases',<CheckSquareOutlined aria-hidden/>,'评价复核'],['/help',<TeamOutlined aria-hidden/>,'学习困难转办'],['/lessons',<BookOutlined aria-hidden/>,'AI 备课']]:[]),
    ['/content',<BookOutlined aria-hidden/>,'教学内容'],...(user.roles.includes('admin')?[['/users',<UserOutlined aria-hidden/>,'账号管理'],['/ai-settings',<BookOutlined aria-hidden/>,'AI 服务状态']]:[]),
  ];
  async function logout() {
    try {
      await api('/auth/logout','POST');
      setCsrf('');
      client.removeQueries({predicate:q=>q.queryKey[0]!=='me'});
      client.setQueryData(['me'],null);
    } catch(e){message.error(e instanceof Error?e.message:'退出失败')}
  }
  return <Auth.Provider value={user}><ScrollToTop/><div className="app-shell">
    {menu&&<div className="sidebar-backdrop" onClick={()=>setMenu(false)}/>}
    <aside className={'sidebar '+(menu?'is-open':'')}><Link to="/" className="brand"><span className="brand-mark"><ReadOutlined aria-hidden/></span><span>知行研学<small>ZHIXING LEARNING</small></span></Link>
      <div className="workspace-label">{user.roles.includes('student')?'我的学习空间':'教学管理空间'}</div>
      <nav>{links.map(([path,icon,label])=><NavLink key={String(path)} to={String(path)} end onClick={()=>setMenu(false)}>{icon}<span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="demo-label">原创示例课程</div><p>以真实作答记录学习，<br/>以可靠依据支持理解。</p><div className="sidebar-user"><Avatar style={{background:'#dce9df',color:'#28594b'}}>{user.name.slice(0,1)}</Avatar><div><strong>{user.name}</strong><small>{user.roles.map(r=>({student:'学生',teacher:'教师',admin:'管理员'}[r]??r)).join(' / ')}</small></div><Tooltip title="退出登录"><Button type="text" aria-label="退出登录" icon={<LogoutOutlined aria-hidden/>} onClick={logout}/></Tooltip></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="topbar-left"><Button className="mobile-toggle" type="text" icon={<MenuOutlined aria-hidden/>} onClick={()=>setMenu(!menu)} aria-label="展开菜单"/><span>知行研学 <span className="topbar-separator">/</span> {user.roles.includes('student')?'学习工作台':'教学工作台'}</span></div><div className="topbar-right"><span className="date-label">{new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'})}</span><Tag>{user.roles.includes('student')?'学习空间':'教学空间'}</Tag><Avatar size="small" style={{background:'#28594b'}}>{user.name.slice(0,1)}</Avatar></div></header>
      <main className="page-content"><Routes>
        <Route path="/" element={user.roles.includes('student')?<TodayV2/>:user.roles.includes('teacher')?<Teacher/>:<Navigate to="/content" replace/>}/>
        <Route path="/learning/projects" element={<Role role="student"><ProjectsV2/></Role>}/>
        <Route path="/learning/projects/:projectId" element={<Role role="student"><ProjectV2/></Role>}/>
        <Route path="/learning/session/:taskId" element={<Role role="student"><StudyV2/></Role>}/>
        <Route path="/learning/library" element={<Role role="student"><LibraryV2/></Role>}/>
        <Route path="/learning/reports" element={<Role role="student"><ReportsV2/></Role>}/>
        <Route path="/learning/assessments" element={<Role role="student"><AssessmentsV2/></Role>}/>
        <Route path="/learning/assessments/:assessmentId" element={<Role role="student"><AssessmentV2/></Role>}/>
        <Route path="/assignments" element={user.roles.includes('teacher')?<TeacherAssignments/>:user.roles.includes('student')?<StudentAssignments/>:<Navigate to="/" replace/>}/>
        <Route path="/assignments/:groupId" element={<Role role="student"><AssignmentWork/></Role>}/>
        <Route path="/practice/:groupId" element={<Role role="student"><AssignmentWork practice/></Role>}/>
        <Route path="/goals" element={<Role role="student"><Goals/></Role>}/>
        <Route path="/knowledge" element={<Role role="student"><KnowledgeStatus/></Role>}/>
        <Route path="/help" element={<Referrals teacher={user.roles.includes('teacher')}/>}/>
        <Route path="/lessons" element={<Role role="teacher"><Lessons/></Role>}/>
        <Route path="/ai-settings" element={<Role role="admin"><AISettings/></Role>}/>
        <Route path="/diagnostic" element={<Navigate to="/mistakes" replace/>}/>
        <Route path="/study/:taskId" element={<Role role="student"><Study/></Role>}/>
        <Route path="/mistakes" element={<Role role="student"><MistakeDiagnoses/></Role>}/>
        <Route path="/reviews" element={<Role role="student"><Reviews/></Role>}/>
        <Route path="/reviews/native/:scopeId" element={<Role role="student"><MasteryReview/></Role>}/>
        <Route path="/history" element={<Role role="student"><History/></Role>}/>
        <Route path="/teacher" element={<Role role="teacher"><Teacher/></Role>}/>
        <Route path="/teacher/attempts/:attemptId" element={<Role role="teacher"><TeacherAttempt/></Role>}/>
        <Route path="/cases" element={<Role role="teacher"><Cases/></Role>}/>
        <Route path="/content" element={<ContentList/>}/>
        <Route path="/sources/:versionId" element={<SourceView/>}/>
        <Route path="/users" element={<Role role="admin"><AdminUsers/></Role>}/>
        <Route path="*" element={<Navigate to="/" replace/>}/>
      </Routes></main><footer className="footer">知行研学 · 让学习留下证据，让进步有迹可循</footer>
    </div>
  </div></Auth.Provider>;
}

export default function App() {
  const me = useQuery<User|null>({queryKey:['me'],queryFn:async()=>{try {const user=await api<User>('/me');setCsrf(user.csrf_token);return user} catch(e){if (e instanceof Error && 'status' in e && e.status===401) return null;throw e}},staleTime:0});
  if (!me.isPending && !me.error && !me.data) return <Login/>;
  return <State query={me}>{me.data&&<Shell user={me.data}/>}</State>;
}
