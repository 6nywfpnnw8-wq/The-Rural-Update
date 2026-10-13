/* Fault tests for archive/homepage cache isolation. No external network. */
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const events={},stored=new Map();
let offline=false,networkBody='HOME',networkStatus=200;
const context={URL,Response,Promise,
  self:{location:{href:'https://example.test/The-Rural-Update/sw.js'},clients:{claim:async()=>{}},skipWaiting:async()=>{},addEventListener:(event,fn)=>events[event]=fn},
  caches:{keys:async()=>[],delete:async()=>true,open:async()=>({put:async(key,response)=>stored.set(key,response),match:async(key)=>{const r=stored.get(key);return r&&r.clone();}})},
  fetch:async()=>{if(offline)throw Error('offline');return new Response(networkBody,{status:networkStatus});}
};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../sw.js'),'utf8'),context);
function request(url,options={}) {
  let promise;
  events.fetch({request:{url,method:'GET',mode:'navigate',headers:new Headers(options.headers||{}),...options},respondWith:p=>promise=p});
  return promise;
}
(async()=>{
 const root='https://example.test/The-Rural-Update/';
 await request(root);networkBody='ARCHIVE';await request(root+'archive/2026-10-08.html');
 offline=true;
 assert.equal(await (await request(root)).text(),'HOME');console.log('PASS: archive cannot poison home cache');
 assert.equal(await (await request(root+'archive/2026-10-08.html')).text(),'ARCHIVE');console.log('PASS: cached archive remains its own page');
 assert.equal((await request(root+'archive/missing.html')).status,503);console.log('PASS: missing offline page is not replaced by homepage');
 offline=false;networkStatus=404;networkBody='NOT FOUND';
 assert.equal((await request(root+'archive/missing.html')).status,404);console.log('PASS: real 404 remains a 404');
 assert.equal(request(root+'audio/2026-10-11.mp3'),undefined);console.log('PASS: audio bypasses document cache');
 assert.equal(request('https://other.test/page'),undefined);console.log('PASS: foreign origins bypass service worker');
})().catch(error=>{console.error(error);process.exit(1);});
