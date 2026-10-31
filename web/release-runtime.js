/* Stable application controls. Daily research never rewrites this file. */
(function () {
  'use strict';
  if (window.ruralUpdateRuntimeLoaded) return;
  window.ruralUpdateRuntimeLoaded = true;
  var archived = document.documentElement.dataset.archived === 'true';
  var edition = document.querySelector('meta[name="edition-date"]');
  var date = edition && edition.content;
  var root = new URL('../', document.currentScript.src);
  function tab(name, fragment) {
    var page = document.getElementById('page-' + name);
    if (!page) return;
    document.querySelectorAll('.page').forEach(function (p) { p.classList.toggle('active', p === page); });
    document.querySelectorAll('.tab-btn').forEach(function (b) {
      var active = b.dataset.tab === name;
      b.classList.toggle('active', active); b.setAttribute('aria-selected', String(active));
    });
    if (fragment) {
      var target = document.getElementById(fragment);
      if (target) target.scrollIntoView({block: 'start'});
    }
    if (name === 'archive') refreshArchive();
  }
  document.addEventListener('click', function (event) {
    var target = event.target.closest('[data-tab]');
    if (!target) return;
    event.preventDefault();
    var fragment = (target.getAttribute('href') || '').replace(/^#/, '');
    tab(target.dataset.tab, fragment);
  });
  function showHash() {
    var hash = location.hash.slice(1);
    if (hash.indexOf('signal-') === 0) tab('signals', hash);
    else if (hash === 'archive') tab('archive');
  }
  window.addEventListener('hashchange', showHash); showHash();
  var loadingArchive = false;
  function refreshArchive() {
    if (loadingArchive) return;
    loadingArchive = true;
    fetch(new URL('archive/catalog.json', root), {cache: 'no-store'})
      .then(function (r) { if (!r.ok) throw Error('catalog'); return r.json(); })
      .then(function (catalog) {
        if (!Array.isArray(catalog.editions)) throw Error('catalog format');
        var section = document.getElementById('page-archive');
        if (!section) return;
        var wrapper = document.createElement('div'); wrapper.className = 'card';
        var heading = document.createElement('h2'); heading.textContent = 'Archive'; wrapper.appendChild(heading);
        var info = document.createElement('p'); info.className = 'meta';
        info.textContent = 'Preserved editions. Missing publication dates are not reconstructed.';
        wrapper.appendChild(info);
        catalog.editions.slice().sort(function (a,b) { return b.date.localeCompare(a.date); }).forEach(function (e) {
          if (e.status !== 'available' || !/^\d{4}-\d{2}-\d{2}$/.test(e.date) || e.path !== 'archive/' + e.date + '.html') return;
          var link = document.createElement('a'); link.className = 'edition-row';
          link.href = new URL(e.path, root).href; link.textContent = e.title || e.date;
          wrapper.appendChild(link);
        });
        section.replaceChildren(wrapper);
      }).catch(function () { /* Keep the compiled, working archive rather than blanking it. */ })
      .finally(function () { loadingArchive = false; });
  }
  function localDate() {
    var parts = new Intl.DateTimeFormat('en-US', {timeZone: 'America/Chicago',year: 'numeric',month: '2-digit',day: '2-digit'}).formatToParts(new Date());
    function p(type) { return parts.find(function(x) { return x.type === type; }).value; }
    return p('year') + '-' + p('month') + '-' + p('day');
  }
  function freshness() {
    if (archived || !date) return;
    var label = document.getElementById('freshness');
    if (!label) return;
    if (!navigator.onLine) label.textContent = 'Offline copy · Edition ' + date;
    else if (date < localDate()) label.textContent = 'Latest available: ' + date + ' · New edition delayed';
    else label.textContent = 'Edition ' + date;
  }
  var audio = document.documentElement.dataset.publicationMode === 'app' ? null : document.getElementById('daily-audio');
  var checkingAudio = false, attempts = 0;
  function checkAudio() {
    if (!date || !audio || checkingAudio || attempts >= 5) return;
    checkingAudio = true; attempts += 1;
    var state = document.getElementById('listen-state');
    var mp3 = new URL('audio/' + date + '.mp3', root);
    var transcript = new URL('transcript/' + date + '.html', root);
    fetch(transcript, {method:'HEAD',cache:'no-store'}).then(function(r) {
      var link = document.getElementById('transcript-link');
      if (r.ok && link) { link.href = transcript.href; link.hidden = false; }
    }).catch(function() {});
    fetch(mp3, {method:'HEAD',cache:'no-store'}).then(function(r) {
      if (!r.ok || !/audio|octet-stream/i.test(r.headers.get('content-type') || '')) throw Error('unavailable');
      if (!audio.src) audio.src = mp3.href;
      audio.hidden = false;
      var link = document.getElementById('listen-link');
      if (link) { link.href = mp3.href; link.hidden = false; }
      if (state) state.textContent = 'Audio available for ' + date;
    }).catch(function() {
      if (state) state.textContent = navigator.onLine ? 'Audio unavailable for this edition. The text and transcript remain available.' : 'Offline. Audio requires a saved copy or a connection.';
      if (attempts < 5) setTimeout(checkAudio,60000);
    }).finally(function() { checkingAudio = false; });
  }
  if (audio) {
    audio.addEventListener('loadedmetadata',function() {
      var target = document.getElementById('listen-meta');
      if (target && Number.isFinite(audio.duration)) {
        var total = Math.round(audio.duration);
        target.textContent = 'Duration ' + Math.floor(total/60) + ':' + String(total%60).padStart(2,'0');
      }
    });
    audio.addEventListener('error',function() {
      var s=document.getElementById('listen-state');
      if(s) s.textContent='Audio could not be played. Use Open audio file or the transcript.';
    });
  }
  function checkNewEdition() {
    if (archived || !navigator.onLine) return;
    fetch(new URL('release.json',root),{cache:'no-store'}).then(function(r) {
      if(!r.ok) throw Error('release unavailable'); return r.json();
    }).then(function(release) {
      if(release.edition_date > date && !document.getElementById('refresh-edition')) {
        var b=document.createElement('button'); b.id='refresh-edition'; b.type='button';
        b.textContent='New edition available: '+release.edition_date+'. Refresh';
        b.addEventListener('click',function(){ location.href=new URL('index.html?release='+release.edition_date+'-'+release.revision,root).href; });
        document.querySelector('.fresh').appendChild(b);
      }
    }).catch(function() {});
  }
  function resume() {
    freshness(); checkNewEdition();
    if (!document.hidden) { attempts=0; checkAudio(); }
  }
  document.addEventListener('visibilitychange',resume);
  window.addEventListener('online',resume); window.addEventListener('offline',freshness);
  freshness(); checkAudio(); checkNewEdition();
  if (!archived && 'serviceWorker' in navigator) {
    navigator.serviceWorker.register(new URL('sw.js',root),{scope:root.pathname,updateViaCache:'none'})
      .then(function(registration) { return registration.update(); }).catch(function() {});
  }
})();

