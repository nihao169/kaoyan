import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './styles.css';
export const queryClient = new QueryClient({defaultOptions:{queries:{retry:false,staleTime:10000,refetchOnWindowFocus:true}}});
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><ConfigProvider virtual={false} locale={zhCN} theme={{token:{motion:false,colorPrimary:'#28594b',colorInfo:'#28594b',borderRadius:8,fontFamily:'"Segoe UI","Microsoft YaHei",sans-serif',colorBgLayout:'#f5f6f3',colorText:'#22342f'}}}>
  <AntApp><QueryClientProvider client={queryClient}><BrowserRouter><App/></BrowserRouter></QueryClientProvider></AntApp>
  </ConfigProvider></React.StrictMode>
);
