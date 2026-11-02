import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const output = ts.transpileModule(fs.readFileSync('lib/data/campaign-estimate.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
new Function('exports', output)(exports);
const { estimateCampaign } = exports;
const plan = (overrides = {}) => ({ targetPrompts: 200, acceptancePercent: 100, runsPerFinal: 1,
  reconstructedPrompts: 0, candidatesPerTarget: 3, engines: [{ name: 'test', eurPerRun: .02 }],
  collectionEur: 13.32, preparationEur: 0, cloudEur: 0, iclEurPerTarget: null,
  alreadyCommittedEur: 0, budgetEur: 20, contingencyPercent: 0, ...overrides });

test('200 final prompts: one run, three total runs, two surfaces; no duplicate screening charge', () => {
  assert.equal(estimateCampaign(plan()).forecastEur, 17.32);
  assert.equal(estimateCampaign(plan({ runsPerFinal: 3 })).forecastEur, 25.32);
  const result = estimateCampaign(plan({ runsPerFinal: 3, engines: [{ name: 'A', eurPerRun: .02 }, { name: 'B', eurPerRun: .02 }] }));
  assert.equal(result.plannedExecutions, 1200);
  assert.equal(result.forecastEur, 37.32);
});
test('screened and rejected candidates cost money; retention is an explicit assumption', () => {
  const result = estimateCampaign(plan({ acceptancePercent: 50, runsPerFinal: 3 }));
  assert.equal(result.discoveryCandidates, 400);
  assert.equal(result.plannedExecutions, 800);
  assert.equal(result.forecastEur, 29.32);
});
test('arbitrary final set sizes scale without a nine-variants-per-cluster assumption', () => {
  assert.equal(estimateCampaign(plan({ targetPrompts: 37 })).plannedExecutions, 37);
  assert.equal(estimateCampaign(plan({ targetPrompts: 500, runsPerFinal: 5 })).plannedExecutions, 2500);
});
test('unknown is not free, and a partial subtotal is never a complete budget check', () => {
  const result = estimateCampaign(plan({ preparationEur: null, alreadyCommittedEur: null }));
  assert.equal(result.complete, false);
  assert.equal(result.totalProjectEur, null);
  assert.equal(result.exceedsBudget, null);
  assert.deepEqual(result.unknownLines, ['Transformation, génération et embeddings']);
});
test('reconstruction includes baseline, ICL and repeated winners; screening is reused', () => {
  const result = estimateCampaign(plan({ targetPrompts: 3, reconstructedPrompts: 3, runsPerFinal: 3, iclEurPerTarget: .01 }));
  assert.equal(result.discoveryCandidates, 0);
  assert.equal(result.reconstructionTargets, 1);
  assert.equal(result.plannedExecutions, 10); // 3 initial + 6 winner repeats + 1 baseline
  assert.equal(result.forecastEur, 13.53);
});
test('commitments and uncertainty are additional, never silently zero', () => {
  const result = estimateCampaign(plan({ contingencyPercent: 20, alreadyCommittedEur: 5 }));
  assert.equal(result.forecastEur, 20.784);
  assert.equal(result.totalProjectEur, 25.784);
  assert.equal(result.exceedsBudget, true);
  assert.equal(result.remainingEur, -5.784);
});
test('invalid or duplicate surfaces and unsafe rates are rejected', () => {
  assert.throws(() => estimateCampaign(plan({ engines: [] })));
  assert.throws(() => estimateCampaign(plan({ acceptancePercent: 0 })));
  assert.throws(() => estimateCampaign(plan({ targetPrompts: Infinity })));
  assert.throws(() => estimateCampaign(plan({ collectionEur: -1 })));
  assert.throws(() => estimateCampaign(plan({ engines: [{ name: 'a', eurPerRun: 0 }, { name: 'a', eurPerRun: 0 }] })));
});


test('full scenario starts with all four distinct surfaces; removal reduces cost', () => {
  const engines = exports.fullSurfaceScenario();
  assert.equal(engines.length, 4);
  assert.equal(new Set(engines.map(e => e.name)).size, 4);
  const parameters = { collectionEur: 11.52, acceptancePercent: 50, runsPerFinal: 3, contingencyPercent: 20 };
  const full = estimateCampaign(plan({ ...parameters, engines }));
  assert.equal(full.plannedExecutions, 3200);
  assert.equal(full.forecastEur, 90.624);
  assert.equal(estimateCampaign(plan({ ...parameters, engines: engines.slice(0, 1) })).forecastEur, 33.024);
});
test('conservative scenario uses highest entered price and preserves unknown and invalid prices', () => {
  const original = [{name:'a', eurPerRun:.02}, {name:'b', eurPerRun:.05}, {name:'c', eurPerRun:null}];
  const result = exports.conservativeEngines(original);
  assert.deepEqual(result.map(e => e.eurPerRun), [.05,.05,null]);
  assert.equal(original[0].eurPerRun,.02);
  assert.throws(() => exports.conservativeEngines([{name:"bad",eurPerRun:-1}]));
  assert.equal(estimateCampaign(plan({engines:result})).complete,false);
});
