import { defineConfig } from '@playwright/test';
import base from './playwright.config';
const live=process.env.ZX_REAL_AI==='1';
export default defineConfig({...base,
  testMatch:'teaching-workflow.spec.ts',timeout:live?600000:120000,
  expect:{timeout:20000},
  webServer:base.webServer instanceof Array?base.webServer.map((s,i)=>i===0?{...s,timeout:180000,env:{...s.env,ZX_TEACHING_FLOW:'1',ZX_REAL_AI:live?'1':'0',ZX_TEACHING_TEST_PROVIDER:live?'0':'1'}}:s):base.webServer,
});
