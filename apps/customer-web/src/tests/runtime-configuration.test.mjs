import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../runtime/configuration.ts', import.meta.url), 'utf8');
assert.match(source, /fallbackRuntimeConfiguration/);
assert.doesNotMatch(source, /localStorage\.setItem\(['"]preview/);
assert.doesNotMatch(source, /javascript:/);
