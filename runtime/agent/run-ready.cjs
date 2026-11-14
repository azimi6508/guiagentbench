// Initialize MCP in the same OpenCode server that handles the evaluated session.
// A separate `opencode mcp list` process cannot establish this guarantee.
const {spawn} = require('node:child_process');
const {readFileSync} = require('node:fs');
const {once} = require('node:events');
const {isDeepStrictEqual} = require('node:util');

function validateConfiguration(effective, config) {
  if (!isDeepStrictEqual(effective.mcp, config.mcp) || !isDeepStrictEqual(effective.permission, config.permission) ||
      !isDeepStrictEqual(effective.compaction, config.compaction) || effective.plugin?.length ||
      Object.keys(effective.agent?.bench?.permission ?? {}).length)
    throw new Error('OpenCode server configuration differs from admitted configuration');
}

function validateDiscovery(status, mcp) {
  if (Object.keys(status).length !== Object.keys(mcp).length ||
      Object.keys(mcp).some(name => status[name]?.status !== 'connected'))
    throw new Error('OpenCode MCP discovery failed before inference: ' + JSON.stringify(status));
}

function persistedEvents(messages, sessionID, seen) {
  if (!Array.isArray(messages) || !messages.length) throw new Error('Missing OpenCode session messages');
  const kinds = {'tool': 'tool_use', 'step-start': 'step_start', 'step-finish': 'step_finish',
    'text': 'text', 'reasoning': 'reasoning', 'compaction': 'compaction'};
  const recovered = [];
  for (const message of messages) {
    if (message.info.error) throw new Error('OpenCode session records an error');
    if (message.info.sessionID !== sessionID) throw new Error('OpenCode message session mismatch');
    for (const part of message.parts) {
      if (part.sessionID !== sessionID) throw new Error('OpenCode part session mismatch');
      if (message.info.role !== 'assistant' || isDeepStrictEqual(seen.get(part.id), part)) continue;
      if (part.type === 'tool' && !['completed', 'error'].includes(part.state.status))
        throw new Error('Unfinished OpenCode tool call');
      if (kinds[part.type]) recovered.push({type: kinds[part.type], timestamp: Date.now(), sessionID,
        source: 'opencode-session-api', part});
    }
  }
  const last = messages.filter(message => message.info.role === 'assistant').at(-1);
  if (last?.info.finish !== 'stop' || !last.info.time?.completed)
    throw new Error('OpenCode persisted session did not finish normally');
  return recovered;
}

async function main() {
  const args = process.argv.slice(2);
  if (args[0] !== 'run') throw new Error('Only run may use the ready launcher');
  const config = JSON.parse(readFileSync('/config/opencode.json', 'utf8'));
  const server = spawn('opencode', ['serve', '--hostname', '127.0.0.1', '--port', '4096', '--print-logs'],
    {stdio: ['ignore', 'ignore', 'inherit']});
  let client;
  const stop = () => { client?.kill('SIGTERM'); server.kill('SIGTERM'); };
  process.on('SIGTERM', stop);
  try {
    const base = 'http://127.0.0.1:4096';
    const deadline = Date.now() + 30000;
    while (true) {
      if (server.exitCode !== null) throw new Error('OpenCode server exited during startup');
      try {
        const response = await fetch(base + '/global/health', {signal: AbortSignal.timeout(1000)});
        if (response.ok) break;
      } catch {}
      if (Date.now() > deadline) throw new Error('OpenCode server readiness timeout');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const get = async path => {
      const response = await fetch(base + path + '?directory=%2Fworkspace', {signal: AbortSignal.timeout(20000)});
      if (!response.ok) throw new Error('OpenCode preflight HTTP ' + response.status);
      return response.json();
    };
    const effective = await get('/config');
    validateConfiguration(effective, config);
    const status = await get('/mcp');
    validateDiscovery(status, config.mcp);
    console.error(JSON.stringify({opencode_preflight: 'pass', mcp: status}));
    const seen = new Map();
    const sessionIDs = new Set();
    let buffer = '';
    let parseError;
    client = spawn('opencode', ['run', '--attach', base, '--dir', '/workspace', ...args.slice(1)],
      {stdio: ['ignore', 'pipe', 'inherit']});
    client.stdout.setEncoding('utf8');
    client.stdout.on('data', chunk => {
      process.stdout.write(chunk); // Keep the CLI stream byte-for-byte.
      buffer += chunk;
      if (buffer.length > 16000000) { parseError = new Error('CLI line budget exceeded'); stop(); return; }
      let end;
      while ((end = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, end);
        buffer = buffer.slice(end + 1);
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          if (event.sessionID) sessionIDs.add(event.sessionID);
          if (event.part) seen.set(event.part.id, event.part);
        } catch (error) { parseError = error; }
      }
    });
    const [code] = await once(client, 'close'); // Also wait for its stdout to drain.
    if (code !== 0 || parseError || buffer.trim()) throw new Error('OpenCode CLI exited with an incomplete stream');
    // v1.18.34's attached CLI does not await its event loop after prompt returns.
    // Recover actual persisted parts, never invent a completion or rerun inference.
    const sessions = await get('/session');
    if (sessions.length !== 1 || [...sessionIDs].some(id => id !== sessions[0].id))
      throw new Error('Unexpected OpenCode sessions');
    const sessionID = sessions[0].id;
    const messages = await get('/session/' + sessionID + '/message');
    const recovered = persistedEvents(messages, sessionID, seen);
    for (const event of recovered) process.stdout.write(JSON.stringify(event) + '\n');
    console.error(JSON.stringify({opencode_session_verified: true, recovered_parts: recovered.length}));
  } finally {
    stop();
  }
}
module.exports = {validateConfiguration, validateDiscovery, persistedEvents};
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
