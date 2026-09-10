(function () {
  const signals = [
    {
      id: 'regionalization',
      title: 'Rural regionalization',
      direction: 'Increasing',
      summary: 'Federal rural transformation awards are increasingly funding shared networks, interoperability, technology, care coordination and regional infrastructure rather than isolated facility-by-facility expansion.',
      why: 'This matters because rural sustainability is increasingly tied to capabilities that can be distributed across geography. The strategic question is not whether every hospital can independently replicate every service, but which capabilities must remain local and which can be organized across a regional network.',
      refs: [
        ['CMS · Rural Health Transformation Program launch and program objectives', 'https://www.cms.gov/newsroom/press-releases/cms-launches-landmark-50-billion-rural-health-transformation-program'],
        ['CMS · New York: $76M for regional networks and technology-enhanced primary care · Sep 4, 2026', 'https://www.cms.gov/newsroom/press-releases/trump-administration-announces-76-million-strengthen-regional-coordination-modernize-healthcare'],
        ['CMS · Michigan: $25M for interoperability, broadband, telehealth and remote monitoring · Sep 4, 2026', 'https://www.cms.gov/newsroom/press-releases/trump-administration-invests-25-million-modernize-healthcare-technology-expand-telehealth-improve']
      ]
    },
    {
      id: 'medicaid-financing',
      title: 'Medicaid financing pressure',
      direction: 'Increasing',
      summary: 'Provider-tax restrictions and forthcoming state-directed-payment limits are tightening major components of hospital Medicaid financing at the same time.',
      why: 'Provider taxes, state-directed payments, DSH, base Medicaid reimbursement and uncompensated care should not be evaluated separately. A state response to one financing restriction can change the economics of the others, making a consolidated facility-level downside model more useful than isolated policy estimates.',
      refs: [
        ['CMS · CMS-2452-P provider-tax proposed rule', 'https://www.cms.gov/newsroom/fact-sheets/amending-indirect-hold-harmless-threshold-health-care-related-taxes-proposed-rule-cms-2452-p'],
        ['KFF · At least 37 states have hospital SDPs potentially affected by future limits · Aug 14, 2026', 'https://www.kff.org/medicaid/at-least-37-states-have-medicaid-state-directed-payments-for-hospital-services-that-could-be-reduced-by-the-2025-reconciliation-law-limits/'],
        ['KFF · Spending on Medicaid State Directed Payments before new limits take effect · Jun 15, 2026', 'https://www.kff.org/medicaid/spending-on-medicaid-state-directed-payments-before-new-limits-take-effect/']
      ]
    },
    {
      id: 'rhc-sustainability',
      title: 'RHC sustainability opportunities',
      direction: 'Improving',
      summary: 'The CY 2027 Physician Fee Schedule proposal includes a direct recurring-payment opportunity for Rural Health Clinics by proposing stand-alone RHC payment for DSMT and MNT services through the All-Inclusive Rate.',
      why: 'The signal is important because rural transformation projects are more durable when grant-funded program development can transition into ordinary reimbursement. The proposal creates a concrete example of aligning chronic-disease capability with a recurring Medicare payment pathway.',
      refs: [
        ['CMS · CY 2027 Physician Fee Schedule proposed rule fact sheet', 'https://www.cms.gov/newsroom/fact-sheets/calendar-year-cy-2027-medicare-physician-fee-schedule-proposed-rule'],
        ['CMS · CMS-1848-P rule page and supporting materials', 'https://www.cms.gov/medicare/payment/fee-schedules/physician/federal-regulation-notices/cms-1848-p'],
        ['CMS · CY 2027 Medicare Shared Savings Program proposals', 'https://www.cms.gov/newsroom/fact-sheets/calendar-year-cy-2027-medicare-physician-fee-schedule-proposed-rule-cms-1848-p-medicare-shared']
      ]
    },
    {
      id: 'payer-friction',
      title: 'Payer administrative friction',
      direction: 'Potentially improving',
      summary: 'UnitedHealthcare has announced rural payment acceleration, broad prior-authorization exemptions for rural providers and additional reductions in authorization requirements. The direction is favorable, but the operational effect still needs to be measured.',
      why: 'Administrative burden changes the effective economics of a payer contract. Faster payment, fewer authorizations, lower denial volume and fewer appeal hours can improve net payment after administrative cost even when nominal negotiated rates do not change.',
      refs: [
        ['UnitedHealthcare · Rural payment acceleration and most prior-authorization exemptions · Apr 20, 2026', 'https://www.unitedhealthgroup.com/newsroom/2026/2026-04-20-uhc-eliminates-most-medical-prior-authorizations-accelerates-payments-for-key-rural-care-hospitals-providers.html'],
        ['UnitedHealthcare · 30% reduction in remaining prior-authorization requirements · May 5, 2026', 'https://www.unitedhealthgroup.com/newsroom/2026/2026-05-05-uhc-cuts-prior-authorization-requirements-by-30-percent.html'],
        ['UnitedHealthcare · Oklahoma included in Rural Payment Acceleration Pilot · Jan 14, 2026', 'https://www.unitedhealthgroup.com/newsroom/2026/2026-01-14-accelerated-medicare-advantage-payments.html']
      ]
    },
    {
      id: 'workforce-localization',
      title: 'Workforce localization',
      direction: 'Increasing',
      summary: 'Federal rural workforce policy continues to invest in training clinicians in rural communities and building local pipelines rather than relying only on downstream recruitment.',
      why: 'Training location matters to long-term workforce strategy. Programs that build local residency, rotation, preceptor and education infrastructure create a stronger pathway from temporary grant support to durable clinical capacity in rural communities.',
      refs: [
        ['CMS · West Virginia: statewide rural recruitment and relocation investment · Sep 9, 2026', 'https://www.cms.gov/newsroom/press-releases/trump-administration-announces-4-8-million-strengthen-west-virginias-rural-healthcare-workforce'],
        ['HHS / HRSA · $11.2M for 15 new rural and tribal physician residency programs · Sep 4, 2026', 'https://www.hhs.gov/press-room/hrsa-awards-11-million-expand-rural-medical-residencies.html'],
        ['HRSA · Rural Residency Planning and Development Program outcomes and resources', 'https://www.hrsa.gov/rural-health/grants/rural-health-research-policy/rrpd'],
        ['HRSA · RRPD funding program and sustainability requirements', 'https://www.hrsa.gov/grants/find-funding/HRSA-26-047']
      ]
    }
  ];

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function signalHref(id) { return '#signal-' + id; }

  function renderSignals() {
    const section = document.getElementById('page-signals');
    if (!section) return;

    const style = document.createElement('style');
    style.textContent = '.signal-index{display:grid;gap:8px}.signal-link{display:block;text-decoration:none;color:inherit;border:1px solid var(--border);border-radius:10px;padding:11px 12px;background:var(--card)}.signal-link:hover,.signal-link:focus{border-color:var(--gold)}.signal-link strong{display:block;color:var(--navy);font-size:13px}.signal-link span{display:block;color:var(--gray);font-size:11.5px;margin-top:2px}.signal-link em{float:right;color:var(--gold);font-style:normal;font-weight:800}.evidence-card{scroll-margin-top:70px}.evidence-card h3{font-size:15px;color:var(--navy);margin:0 0 4px}.direction{display:inline-block;font-size:9px;text-transform:uppercase;letter-spacing:.05em;font-weight:800;border-radius:999px;padding:3px 7px;background:var(--soft);color:var(--navy);margin-bottom:9px}.evidence-card p{font-size:12.5px;margin:0 0 9px}.evidence-card h4{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);margin:13px 0 6px}.reading-link{display:block;padding:8px 9px;border-top:1px solid var(--border);color:var(--navy2);font-size:11.5px;text-decoration:none}.reading-link:first-of-type{border-top:0}.reading-link:after{content:" ↗"}.back-signals{display:inline-block;margin-top:10px;font-size:10.5px;color:var(--navy2);text-decoration:none;font-weight:700}';
    document.head.appendChild(style);

    let html = '<div class="card"><h2>Signals &amp; Trends</h2><p class="meta" style="margin:0 0 10px;">Each signal links to the evidence and reading that supports the directional assessment. These are public-source indicators, not forecasts.</p><div class="signal-index">';
    signals.forEach(function(s) {
      html += '<a class="signal-link" href="' + signalHref(s.id) + '"><em>›</em><strong>' + esc(s.title) + ': ' + esc(s.direction) + '</strong><span>' + esc(s.summary) + '</span></a>';
    });
    html += '</div></div>';

    html += '<div class="card"><h2>Executive Interpretation</h2><p>The strategic pattern is consistent: rural sustainability is moving toward regional capability, differentiated local services, stronger payer intelligence and explicit post-grant operating models. The leadership advantage will come from deciding what must remain local, what can be shared and what no longer justifies duplicated cost.</p></div>';

    html += '<div id="signal-evidence"><div class="card"><h2>Signal Evidence &amp; Reading Library</h2><p class="meta">Use these references to validate the signal, understand the underlying policy or market change, and read beyond the daily brief.</p></div>';
    signals.forEach(function(s) {
      html += '<div class="card evidence-card" id="signal-' + esc(s.id) + '"><h3>' + esc(s.title) + '</h3><span class="direction">Direction: ' + esc(s.direction) + '</span><p><strong>What the signal indicates:</strong> ' + esc(s.summary) + '</p><p><strong>Why it matters:</strong> ' + esc(s.why) + '</p><h4>Evidence &amp; Further Reading</h4>';
      s.refs.forEach(function(r) {
        html += '<a class="reading-link" href="' + esc(r[1]) + '" target="_blank" rel="noopener">' + esc(r[0]) + '</a>';
      });
      html += '<a class="back-signals" href="#page-signals">Back to signals ↑</a></div>';
    });
    html += '</div>';
    section.innerHTML = html;

    const homepageSignals = document.querySelectorAll('#page-today .signal-grid .sig');
    homepageSignals.forEach(function(node) {
      const text = node.textContent.toLowerCase();
      let id = null;
      if (text.includes('medicaid')) id = 'medicaid-financing';
      else if (text.includes('regional')) id = 'regionalization';
      else if (text.includes('payer')) id = 'payer-friction';
      else if (text.includes('workforce')) id = 'workforce-localization';
      if (!id) return;
      node.style.cursor = 'pointer';
      node.setAttribute('role', 'link');
      node.setAttribute('tabindex', '0');
      const go = function() {
        const btn = document.querySelector('.tab-btn[onclick*="signals"]');
        if (btn && typeof window.showTab === 'function') window.showTab('signals', btn);
        setTimeout(function(){ const target = document.getElementById('signal-' + id); if (target) target.scrollIntoView({behavior:'smooth',block:'start'}); }, 50);
      };
      node.addEventListener('click', go);
      node.addEventListener('keydown', function(e){ if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); go(); } });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderSignals);
  else renderSignals();
})();
