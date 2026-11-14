// Credential-free upstream stand-in for the unmodified pinned Cursor client.
// Load only shipped protocol descriptors; never invoke the CLI entry point.
const fs = require('fs');
const Module = require('module');
const path = require('path');
const http = require('http');
const bundle = '/opt/cursor/index.js';
const marker = 'var __webpack_exports__=__webpack_require__("./src/main.tsx")';
let source = fs.readFileSync(bundle, 'utf8');
if (source.split(marker).length !== 2) throw Error('Protocol descriptor pin differs');
const mod = {exports: {}};
new Function('require', '__filename', '__dirname', 'module', 'exports', source.replace(marker, 'module.exports=__webpack_require__'))(
  Module.createRequire(bundle), bundle, path.dirname(bundle), mod, mod.exports);
const proto = mod.exports('../proto/dist/generated/agent/v1/agent_service_pb.js');
const types = new Map();
for (const name of Object.keys(mod.exports.m).filter(n => /proto\/dist\/generated\/.+_pb\.js$/.test(n))) {
  for (const value of Object.values(mod.exports(name))) {
    if (typeof value === 'function' && value.$) {
      try { types.set(value.$()[0].split('|')[0], value); } catch {}
    }
  }
}
const model = 'fixture-model';
const pending = new Map();
function frame(value, end=false, binary=false) {
  const data = binary && !end ? Buffer.from(proto.Oy.fromJson(value).toBinary()) : Buffer.from(JSON.stringify(value));
  const header = Buffer.alloc(5); header[0] = end ? 2 : 0; header.writeUInt32BE(data.length, 1);
  return Buffer.concat([header, data]);
}
function send(session, value) { session.res.write(frame(value, false, session.binary)); }
function finish(session) {
  send(session, {interactionUpdate: {textDelta: {text: 'Control completed.'}}});
  send(session, {interactionUpdate: {turnEnded: {}}});
  session.res.end(frame({}, true));
}
function next(session) {
  const file='/policy/control-delay-ms';
  const delay=fs.existsSync(file)?Number(fs.readFileSync(file,'utf8')):0;
  if(delay) {setTimeout(()=>nextNow(session),delay);return;}
  nextNow(session);
}
function nextNow(session) {
  const steps=JSON.parse(fs.readFileSync('/policy/control-steps.json','utf8'));
  if(session.step>=steps.length) {finish(session);return;}
  const step=steps[session.step];
  const id='control-'+(++session.step);
  const args={name:step.name,toolName:step.name,serverIdentifier:'bench',providerIdentifier:'bench',toolCallId:id,args:step.arguments};
  session.current={args,id};
  send(session,{interactionUpdate:{toolCallStarted:{callId:id,toolCall:{mcpToolCall:{args},toolCallId:id,startedAtMs:'1'}}}});
  send(session,{execServerMessage:{id:session.step,execId:id,mcpArgs:args}});
}
function handleMessage(session, message) {
  const value = message;
  console.log(JSON.stringify({event: 'message', kind: Object.keys(value)[0]}));
  if (value.runRequest) {
    const request = value.runRequest;
    console.log(JSON.stringify({event: 'request', model: request.modelDetails?.modelId, tools: request.mcpTools,
      excluded: request.excludeWorkspaceContext}));
    send(session, {interactionUpdate: {textDelta: {text: 'Scripted client control.'}}});
    session.step=0;
    next(session);
  } else if (value.execClientMessage) {
    const response = value.execClientMessage;
    console.log(JSON.stringify({event: 'exec_result', value: response}));
    // Large image return payloads already travel in the real client-to-provider
    // stream. The synthetic UI update need not duplicate those image bytes.
    send(session, {interactionUpdate: {toolCallCompleted: {callId:session.current.id,toolCall:{mcpToolCall:{args:session.current.args},toolCallId:session.current.id,startedAtMs:'1',completedAtMs:'2'}}}});
    next(session);
  }
}
http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/bench/catalog-ready') {
    res.writeHead(200, {'Content-Length':'0'});res.end();return;
  }
  const chunks=[]; for await (const chunk of req) chunks.push(chunk);
  let data=Buffer.concat(chunks);
  if (req.headers['content-encoding']==='gzip') data=require('zlib').gunzipSync(data);
  const method = req.url.split('/').pop();
  console.log(JSON.stringify({event: 'request_path', path: req.url, type: req.headers['content-type'], allowed: req.headers['x-cursor-agent-allowed-tools']}));
  const ct=req.headers['content-type'] || '';
  if (ct.includes('connect+')) data=data.subarray(5);
  let input={};
  try { input=JSON.parse(data.toString()); }
  catch { const type=types.get(method === 'RunSSE' ? 'BidiRequestId' : method+'Request'); if(type) input=type.fromBinary(data).toJson(); }
  if (method === 'RunSSE') {
    res.writeHead(200, {'Content-Type':ct.includes('proto')?'application/connect+proto':'application/connect+json'});
    const id=input.requestId;
    const session = pending.get(id) || {queue:[]}; session.res=res; session.binary=ct.includes('proto'); pending.set(id,session);
    for (const message of session.queue) handleMessage(session, message);
    return;
  }
  function reply(value) {
    if (ct.includes('proto')) {
      const type=types.get(method+'Response');
      res.writeHead(200, {'Content-Type':'application/proto'});
      res.end(type ? type.fromJson(value).toBinary() : Buffer.alloc(0));
    } else { res.writeHead(200, {'Content-Type':'application/json'}); res.end(JSON.stringify(value)); }
  }
  if (method === 'BidiAppend') {
    console.log(JSON.stringify({event:'bidi', input}));
    const id=input.requestId?.requestId;
    const session = pending.get(id) || {queue:[]}; pending.set(id,session);
    let message;
    try { message=JSON.parse(input.data); }
    catch { message=proto.KS.fromBinary(input.dataBinary ? Buffer.from(input.dataBinary, 'base64') : Buffer.from(input.data||'', 'hex')).toJson(); }
    if (session.res) handleMessage(session,message); else session.queue.push(message);
    reply({}); return;
  }
  if (method === 'GetUsableModels') {reply({models:[{modelId:model,displayModelId:model,displayName:model,displayNameShort:model}]});return;}
  if (method === 'AvailableModels') {reply({modelNames:[model]});return;}
  if (method === 'GetDefaultModelForCli') {reply({model:{modelId:model,displayName:model}});return;}
  reply({});
}).listen(8080, '0.0.0.0');
