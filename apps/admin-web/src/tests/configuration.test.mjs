import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../../app/management/configuration/page.tsx', import.meta.url), 'utf8');
assert.match(page, /Configuration Center/);
assert.match(page, /without raw JSON editors/);
const types = readFileSync(new URL('../configuration/types.ts', import.meta.url), 'utf8');
assert.match(types, /configuration\.rollback/);
assert.match(types, /media_assets\.manage/);
