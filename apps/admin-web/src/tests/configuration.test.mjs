import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../../app/management/configuration/page.tsx', import.meta.url), 'utf8');
const studio = readFileSync(new URL('../configuration/ConfigurationStudio.tsx', import.meta.url), 'utf8');
const api = readFileSync(new URL('../configuration/api.ts', import.meta.url), 'utf8');
assert.match(page, /ConfigurationStudio/);
assert.match(studio, /نام فارسی/);
assert.match(studio, /تم تاریک/);
assert.match(studio, /ذخیره و اعتبارسنجی/);
assert.match(studio, /انتشار برای همه سطوح/);
assert.match(api, /refreshOnce/);
assert.match(api, /x-csrf-token/);
assert.doesNotMatch(studio, /textarea[^>]*json/i);
const types = readFileSync(new URL('../configuration/types.ts', import.meta.url), 'utf8');
assert.match(types, /configuration\.rollback/);
assert.match(types, /media_assets\.manage/);
