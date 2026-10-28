import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
const data=path.resolve('..','.runtime','e2e-'+Date.now());
export default defineConfig({
  testDir:'./tests',testMatch:'platform.spec.ts',fullyParallel:false,workers:1,timeout:60000,
  expect:{timeout:10000},retries:0,
  reporter:[['list'],['html',{open:'never'}]],
  use:{baseURL:'http://127.0.0.1:5181',trace:'retain-on-failure',screenshot:'only-on-failure',
    ...devices['Desktop Chrome'],channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'},
  webServer:[
    {command:'..\\.venv\\Scripts\\python.exe ..\\scripts\\e2e_server.py',url:'http://127.0.0.1:8001/health/ready',timeout:90000,reuseExistingServer:false,env:{ZX_E2E_DATA:data,PYTHONUTF8:'1'}},
    {command:'npm run dev -- --port 5181',url:'http://127.0.0.1:5181',timeout:90000,reuseExistingServer:false,env:{API_TARGET:'http://127.0.0.1:8001'}},
  ],
});
