const {test} = require('node:test');
const assert = require('node:assert/strict');
const {validateConfiguration, validateDiscovery, persistedEvents} = require('../runtime/agent/run-ready.cjs');

test('configuration drift is rejected, empty normalized permissions are allowed', () => {
  const config = {mcp: {}, permission: {'*': 'deny'}, compaction: {auto: false, prune: false}};
  validateConfiguration({...config, agent: {bench: {permission: {}}}}, config);
  for (const changes of [{permission: {'*': 'allow'}}, {mcp: {extra: {}}},
    {compaction: {auto: true}}, {plugin: ['unexpected']}, {agent: {bench: {permission: {bash: 'allow'}}}}])
    assert.throws(() => validateConfiguration({...config, ...changes}, config));
});

test('missing, disconnected, or extra MCP servers are rejected before inference', () => {
  const mcp = {gui: {type: 'remote'}};
  validateDiscovery({gui: {status: 'connected'}}, mcp);
  validateDiscovery({}, {});
  for (const status of [{}, {gui: {status: 'failed'}}, {gui: {status: 'connected'}, extra: {status: 'connected'}}])
    assert.throws(() => validateDiscovery(status, mcp));
});

const info = {role: 'assistant', sessionID: 's', finish: 'stop', time: {completed: 123}};
const part = {id: 'p', sessionID: 's', type: 'step-finish', reason: 'stop'};

test('a lost stream event is restored only from the persisted session', () => {
  const events = persistedEvents([{info, parts: [part]}], 's', new Map());
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'step_finish');
  assert.equal(events[0].source, 'opencode-session-api');
  assert.equal(events[0].part, part);
});

test('object key order does not duplicate an already delivered event', () => {
  const reordered = {reason: 'stop', type: 'step-finish', sessionID: 's', id: 'p'};
  assert.deepEqual(persistedEvents([{info, parts: [part]}], 's', new Map([['p', reordered]])), []);
});

test('crashed, unfinished, and foreign sessions cannot manufacture success', () => {
  for (const badInfo of [{...info, error: {name: 'crash'}}, {...info, finish: 'length'},
    {...info, time: {}}, {...info, sessionID: 'other'}])
    assert.throws(() => persistedEvents([{info: badInfo, parts: [part]}], 's', new Map()));
  assert.throws(() => persistedEvents([], 's', new Map()));
  assert.throws(() => persistedEvents([{info, parts: [{...part, sessionID: 'other'}]}], 's', new Map()));
  assert.throws(() => persistedEvents([{info, parts: [{...part, type: 'tool', state: {status: 'running'}}]}], 's', new Map()));
});
