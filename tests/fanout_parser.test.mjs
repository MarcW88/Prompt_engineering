import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source = fs.readFileSync('app/api/analyze/route.ts', 'utf8');
const fn = source.slice(source.indexOf('function deepSearchQueries'), source.indexOf('\nfunction normalize'));
const js = ts.transpile(fn, { target: ts.ScriptTarget.ES2020 });
const parse = new Function(`${js}; return deepSearchQueries;`)();
test('production manual parser retains all nested query blocks', () => {
  assert.deepEqual(parse({ web_search_query: 'one', metadata: { search_model_queries: { queries: ['two', 'three', 'four'] } }, blocks: [{ search_queries: [{ q: 'five' }] }, { web_search_queries: ['six', 'one'] }] }), ['one', 'two', 'three', 'four', 'five', 'six']);
});
test('empty and malformed query nodes do not invent strings', () => {
  assert.deepEqual(parse({ queries: [null, {}, 42, { query: 'valid' }] }), ['valid']);
});
