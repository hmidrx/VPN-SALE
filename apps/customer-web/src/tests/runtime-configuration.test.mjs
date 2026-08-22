import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../runtime/configuration.ts', import.meta.url), 'utf8');
assert.match(source, /fallbackRuntimeConfiguration/);
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
