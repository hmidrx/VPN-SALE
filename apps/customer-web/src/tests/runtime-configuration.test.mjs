import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../runtime/configuration.ts', import.meta.url), 'utf8');
assert.match(source, /fallbackRuntimeConfiguration/);
assert.match(source, /if \(!base\) return fallbackRuntimeConfiguration/);
assert.match(source, /AbortSignal\.timeout\(2_500\)/);
assert.match(source, /API_INTERNAL_BASE_URL/);
assert.doesNotMatch(source, /localStorage\.setItem\(['"]preview/);
assert.doesNotMatch(source, /javascript:/);

const provider = readFileSync(new URL('../runtime/RuntimeConfigurationProvider.tsx', import.meta.url), 'utf8');
const layout = readFileSync(new URL('../../app/layout.tsx', import.meta.url), 'utf8');
const app = readFileSync(new URL('../components/CustomerApp.tsx', import.meta.url), 'utf8');
const commerce = readFileSync(new URL('../components/Commerce.tsx', import.meta.url), 'utf8');
assert.match(provider, /--color-primary/);
assert.match(layout, /getRuntimeConfiguration/);
assert.match(app, /useRuntimeConfiguration/);
assert.match(app, /CheckoutSessionPage/);
assert.match(commerce, /getCheckout/);
assert.doesNotMatch(readFileSync(new URL('../../app/customer.css', import.meta.url), 'utf8'), /DR\.PING/);

const runtimeTypes = readFileSync(new URL('../runtime/runtime-types.ts', import.meta.url), 'utf8');
assert.match(runtimeTypes, /logo_asset_reference/);
assert.match(app, /configuration\/media/);
assert.match(app, /href="\/app"/);
