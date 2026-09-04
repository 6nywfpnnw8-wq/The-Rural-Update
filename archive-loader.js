(function () {
  const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatShort(dateString) {
    const d = new Date(dateString + 'T12:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function weekday(dateString) {
    const d = new Date(dateString + 'T12:00:00');
    return d.toLocaleDateString('en-US', { weekday: 'long' });
  }

  function monthKey(dateString) {
    const d = new Date(dateString + 'T12:00:00');
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  }

  function monthLabel(dateString) {
    const d = new Date(dateString + 'T12:00:00');
    return MONTHS[d.getMonth()] + ' ' + d.getFullYear();
  }

  function normalizePath(path) {
    if (!path) return '#';
    return path.replace(/^\.\//, '');
  }

  function renderArchive(catalog) {
    const section = document.getElementById('page-archive');
    if (!section || !catalog || !Array.isArray(catalog.editions)) return;

    const editions = catalog.editions
      .filter(e => e && e.status === 'available' && e.date && e.path)
      .slice()
      .sort((a, b) => String(b.date).localeCompare(String(a.date)));

    if (!editions.length) {
      section.innerHTML = '<div class="latest"><p class="eyebrow">Archive</p><h3>No published editions yet</h3><p>The archive catalog is valid, but it does not currently contain any available editions.</p></div>';
      return;
    }

    const latest = editions[0];
    let html = '<div class="latest">' +
      '<p class="eyebrow">Latest Archived Edition</p>' +
      '<h3>' + esc(latest.title || latest.date) + '</h3>' +
      '<p>This archive is generated from <code>archive/catalog.json</code>. Only editions that actually exist in the repository are listed.</p>' +
      '<p class="meta">Catalog updated: ' + esc(catalog.updated || 'not specified') + ' &nbsp;·&nbsp; ' + editions.length + ' edition' + (editions.length === 1 ? '' : 's') + ' available</p>' +
      '</div>';

    let activeMonth = null;
    editions.forEach(function (edition) {
      const key = monthKey(edition.date);
      if (key !== activeMonth) {
        activeMonth = key;
        html += '<div class="month-title">' + esc(monthLabel(edition.date)) + '</div>';
      }
      html += '<a class="edition-row" href="' + esc(normalizePath(edition.path)) + '">' +
        '<div class="left"><span class="date">' + esc(formatShort(edition.date)) + '</span>' +
        '<span class="weekday">' + esc(weekday(edition.date)) + '</span></div>' +
        '<span class="chev">›</span></a>';
    });

    html += '<p class="meta" style="margin-top:16px;">Archive entries are rendered from the repository catalog. Missing or unpublished historical files are intentionally omitted rather than linked as dead pages.</p>';
    section.innerHTML = html;
  }

  function loadArchive() {
    const cacheBuster = Date.now();
    fetch('./archive/catalog.json?v=' + cacheBuster, { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) throw new Error('Archive catalog unavailable');
        return response.json();
      })
      .then(renderArchive)
      .catch(function () {
        const section = document.getElementById('page-archive');
        if (section) {
          section.innerHTML = '<div class="latest"><p class="eyebrow">Archive</p><h3>Archive temporarily unavailable</h3><p>The catalog could not be loaded. The current brief remains available above.</p></div>';
        }
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadArchive);
  } else {
    loadArchive();
  }
})();
