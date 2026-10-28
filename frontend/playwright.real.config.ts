import { defineConfig } from '@playwright/test';
import base from './playwright.config';
process.env.ZX_REAL_AI='1';
export default defineConfig(base,{testMatch:'real-ai.live.ts',timeout:180000,expect:{timeout:20000}});
