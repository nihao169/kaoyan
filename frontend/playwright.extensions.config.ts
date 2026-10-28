import { defineConfig } from '@playwright/test';
import base from './playwright.config';
export default defineConfig(base,{testMatch:'extensions.spec.ts',timeout:120000});
