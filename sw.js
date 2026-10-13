/* Navigation caches use exact paths. An archive can never overwrite the homepage. */
const CACHE='the-rural-update-release-v11';
const ROOT=new URL('./',self.location.href);
const CURRENT=new URL('index.html',ROOT).href;
self.addEventListener('install',event=>{event.waitUntil(self.skipWaiting());});
self.addEventListener('activate',event=>{event.waitUntil((async()=>{
  const keys=await caches.keys();
  await Promise.all(keys.filter(k=>k.startsWith('the-rural-update-')&&k!==CACHE).map(k=>caches.delete(k)));
  await self.clients.claim();
})());});
self.addEventListener('fetch',event=>{
  const request=event.request,url=new URL(request.url);
  if(request.method!=='GET'||url.origin!==ROOT.origin||!url.pathname.startsWith(ROOT.pathname))return;
  if(request.headers.has('range')||url.pathname.endsWith('.mp3'))return;
  if(url.pathname.endsWith('/release.json')||url.pathname.endsWith('/podcast.xml')||url.pathname.endsWith('/archive/catalog.json')){
    event.respondWith(fetch(request,{cache:'no-store'}));return;
  }
  const isHome=url.pathname===ROOT.pathname||url.pathname===new URL(CURRENT).pathname;
  const cacheKey=isHome?CURRENT:url.origin+url.pathname;
  event.respondWith((async()=>{
    const cache=await caches.open(CACHE);
    try{
      const response=await fetch(request,{cache:'no-store'});
      if(response.ok){await cache.put(cacheKey,response.clone());}
      // Preserve a real 404 instead of masking it with today's page.
      return response;
    }catch(error){
      const saved=await cache.match(cacheKey);
      if(saved)return saved;
      if(request.mode==='navigate')return new Response('<h1>Offline</h1><p>This page has not been saved. Reconnect to open it.</p>',{status:503,headers:{'Content-Type':'text/html; charset=utf-8'}});
      return Response.error();
    }
  })());
});
