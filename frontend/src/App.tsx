import { createContext, useContext, useLayoutEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { App as AntApp, Avatar, Button, Form, Input, Tag, Tooltip } from 'antd';
import { BookOutlined, CalendarOutlined, CheckSquareOutlined, EditOutlined, FileTextOutlined, HomeOutlined, LogoutOutlined, MenuOutlined, ReadOutlined, TeamOutlined, UserOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { api, setCsrf, type User } from './api';
import { State } from './ui';
import { Home, Goals, Diagnostic, Study, Mistakes, Reviews, History } from './student';
import { Teacher, TeacherAttempt, Cases, AdminUsers } from './teacher';
import { ContentList, SourceView } from './content';
import { AISettings, KnowledgeStatus, Referrals, Lessons } from './extensions';

const Auth = createContext<User | null>(null);
export function useUser() { return useContext(Auth)!; }

function Login() {
  const [busy,setBusy] = useState(false);
  const {message} = AntApp.useApp();
  const client = useQueryClient();
  const navigate = useNavigate();
  async function login(values:{username:string;password:string}) {
    setBusy(true);
    try {
      await api('/auth/login','POST',values);
      const user = await api<User>('/me');
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
  </div><div className="login-form"><div className="login-box"><Tag color="green">学习工作台</Tag><h2>欢迎回来</h2><p className="muted">登录后继续你的学习与教学工作。</p>
    <Form layout="vertical" onFinish={login} initialValues={{username:'student'}} requiredMark={false}>
      <Form.Item name="username" label="账号" rules={[{required:true,message:'请输入账号'}]}><Input size="large" prefix={<UserOutlined aria-hidden/>} autoComplete="username"/></Form.Item>
      <Form.Item name="password" label="密码" rules={[{required:true,message:'请输入密码'}]}><Input.Password size="large" autoComplete="current-password" placeholder="请输入密码"/></Form.Item>
      <Button type="primary" block size="large" htmlType="submit" loading={busy}>进入工作台 <ArrowRightOutlined aria-hidden/></Button>
    </Form>
    <div className="demo-accounts"><strong>本地演示账号</strong><p>学生 student　教师 teacher　管理员 admin</p><p>统一密码：<code>Zhixing2026!</code></p><small>示例内容需教师审核发布后才能开始学习。</small></div>
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
    ['/',<HomeOutlined aria-hidden/>,'学习首页'],['/goals',<CalendarOutlined aria-hidden/>,'目标与安排'],['/diagnostic',<CheckSquareOutlined aria-hidden/>,'基础诊断'],['/knowledge',<BookOutlined aria-hidden/>,'知识点诊断'],['/mistakes',<EditOutlined aria-hidden/>,'错题与补学'],['/reviews',<ReadOutlined aria-hidden/>,'复习计划'],['/history',<FileTextOutlined aria-hidden/>,'学习记录'],['/help',<TeamOutlined aria-hidden/>,'教师帮助'],
  ] : [
    ...(user.roles.includes('teacher')? [['/',<HomeOutlined aria-hidden/>,'教学概览'],['/teacher',<TeamOutlined aria-hidden/>,'班级与作答'],['/cases',<CheckSquareOutlined aria-hidden/>,'评价复核'],['/help',<TeamOutlined aria-hidden/>,'学习困难转办'],['/lessons',<BookOutlined aria-hidden/>,'AI 备课']]:[]),
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
    <div className="main-shell"><header className="topbar"><div className="topbar-left"><Button className="mobile-toggle" type="text" icon={<MenuOutlined aria-hidden/>} onClick={()=>setMenu(!menu)} aria-label="展开菜单"/><span>知行研学 <span className="topbar-separator">/</span> {user.roles.includes('student')?'学习工作台':'教学工作台'}</span></div><div className="topbar-right"><span className="date-label">{new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'})}</span><Tag>演示机构</Tag><Avatar size="small" style={{background:'#28594b'}}>{user.name.slice(0,1)}</Avatar></div></header>
      <main className="page-content"><Routes>
        <Route path="/" element={user.roles.includes('student')?<Home/>:user.roles.includes('teacher')?<Teacher/>:<Navigate to="/content" replace/>}/>
        <Route path="/goals" element={<Role role="student"><Goals/></Role>}/>
        <Route path="/knowledge" element={<Role role="student"><KnowledgeStatus/></Role>}/>
        <Route path="/help" element={<Referrals teacher={user.roles.includes('teacher')}/>}/>
        <Route path="/lessons" element={<Role role="teacher"><Lessons/></Role>}/>
        <Route path="/ai-settings" element={<Role role="admin"><AISettings/></Role>}/>
        <Route path="/diagnostic" element={<Role role="student"><Diagnostic/></Role>}/>
        <Route path="/study/:taskId" element={<Role role="student"><Study/></Role>}/>
        <Route path="/mistakes" element={<Role role="student"><Mistakes/></Role>}/>
        <Route path="/reviews" element={<Role role="student"><Reviews/></Role>}/>
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
