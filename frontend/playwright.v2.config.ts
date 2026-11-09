import { defineConfig } from '@playwright/test';
import base from './playwright.config';
export default defineConfig({...base,testMatch:['v2.spec.ts','v2-native.spec.ts'],timeout:120000,
  webServer:base.webServer instanceof Array?base.webServer.map((server,index)=>index===0?{...server,env:{...server.env,ZX_V2_TEST_PROVIDER:'1'},timeout:120000}:server):base.webServer});
