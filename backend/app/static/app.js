let token = localStorage.getItem('epic_token');
let currentDebate = null;
let currentUser = null;
let currentLibraryEntry = null;
let socket = null;
const $ = id => document.getElementById(id);

const ANSWERS = {yes: 'Yes', no: 'No', gap: 'Gap'};
const STATUSES = {verified: 'Verified', supported: 'Supported', disputed: 'Disputed', unresolved: 'Unresolved', stale: 'Stale'};

async function api(path, opts = {}) {
  opts.headers = {...(opts.headers || {}), 'Content-Type': 'application/json'};
  if (token) opts.headers.Authorization = 'Bearer ' + token;
  const response = await fetch(path, opts);
  if (!response.ok) {
    let data = {};
    try { data = await response.json(); } catch { /* keep the fallback message */ }
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : (detail?.message || JSON.stringify(detail) || 'Request failed'));
  }
  if (response.status === 204) return null;
  return response.json();
}

function msg(id, text, ok = false) {
  $(id).textContent = text;
  $(id).className = 'notice ' + (ok ? 'ok' : 'error');
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[character]));
}

function blank(value) {
  const text = value == null ? '' : String(value).trim();
  return text || 'not recorded';
}

function scoreText(value) {
  return value == null || value === '' ? 'unknown' : String(value);
}

function formatFactor(value) {
  if (value == null || value === '') return 'unknown';
  return (Math.round(Number(value) * 100) / 100).toFixed(2);
}

function formatScore(value) {
  if (value == null || value === '') return 'Unknown – not yet rated';
  const rounded = (Math.round(Number(value) * 100) / 100).toFixed(2);
  const percent = Math.round(Number(value) * 100);
  return `${rounded} on a 0–1 scale (${percent}%)`;
}

function formatWhen(value) {
  if (!value) return '';
  let text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}T/.test(text) && !/(?:Z|[+-]\d{2}:?\d{2})$/.test(text)) text += 'Z';
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return String(value);
  try {
    const formatted = date.toLocaleString(undefined, {year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
    const zone = date.toLocaleTimeString(undefined, {timeZoneName: 'short'}).split(' ').pop();
    return zone && zone !== formatted ? `${formatted} ${zone}` : date.toUTCString();
  } catch {
    return date.toUTCString();
  }
}

function written(map, value) {
  return map[value] || (value ? value.charAt(0).toUpperCase() + value.slice(1) : 'Not recorded');
}

function confidenceBlock(confidence) {
  if (!confidence) return '<p><b>Confidence:</b> Unknown – not yet rated</p>';
  if (confidence.not_factually_answerable) {
    return `<p><b>Not factually answerable.</b> This question has no factual answer. ${esc(confidence.answerability_reason || '')}</p>`;
  }
  const label = confidence.label || (confidence.confidence_score == null ? 'Unknown – not yet rated' : 'Rated');
  const factors = (confidence.factors || []).map(factor =>
    `<li><b>${esc(factor.name)}</b>: ${esc(formatFactor(factor.value))}. ${esc(factor.detail || '')}</li>`
  ).join('');
  const automated = confidence.automated_source_check
    ? `<p>Automated source check: ${esc(confidence.automated_source_check)}. ${esc(confidence.automated_source_check_detail || 'Automated lookup of cited sources is not implemented.')}</p>`
    : '';
  const missing = confidence.cited_source_note ? `<p>${esc(confidence.cited_source_note)}</p>` : '';
  const contradictions = (confidence.contradicting_sources || []).length
    ? `<p><b>Contradicting sources:</b> ${(confidence.contradicting_sources || []).map(source => esc(source.title || ('Source #' + source.id))).join(', ')}</p>`
    : '';
  return `<div class="confidence"><p><b>Confidence:</b> ${esc(formatScore(confidence.confidence_score))}. <b>${esc(label)}</b></p>${missing}${contradictions}${factors ? `<ul>${factors}</ul>` : ''}${automated}</div>`;
}

function confidenceList(value) {
  if (!value) return confidenceBlock(null);
  if (Array.isArray(value)) {
    if (!value.length) return confidenceBlock(null);
    return value.map((item, index) => `<div><p><b>Recorded breakdown ${index + 1}</b></p>${confidenceBlock(item)}</div>`).join('');
  }
  return confidenceBlock(value);
}

function historyBlock(notes) {
  const rows = notes || [];
  if (!rows.length) return '<div class="history"><p><b>Status history:</b> none recorded</p></div>';
  return `<div class="history"><p><b>Status history</b></p><ul>${rows.map(note => `<li>${esc(note.note)}</li>`).join('')}</ul></div>`;
}

function flagBlock(flags, check) {
  const rows = flags || [];
  const items = rows.length
    ? rows.map(flag => `<li><b>${esc(flag.kind)} / ${esc(flag.dimension)}:</b> ${esc(flag.note)} Entered evidence scope: ${esc(flag.source_text)}. Claim: ${esc(flag.claim_text)}.</li>`).join('')
    : '<li>No scope, overgeneralization, or outlier flag.</li>';
  return `<div class="scope-flags"><p><b>Scope review</b></p><ul>${items}</ul>${check ? `<p>${esc(check)}</p>` : ''}</div>`;
}

function scopeLine(item) {
  return `Population ${esc(blank(item.scope_population))}; timeframe ${esc(blank(item.scope_timeframe))}; geography ${esc(blank(item.scope_geography))}; metric ${esc(blank(item.scope_metric))}; study type ${esc(blank(item.scope_study_type))}; sample size ${esc(blank(item.scope_sample_size))}.`;
}

function reevaluationForm(kind, id) {
  return `<form class="reeval" data-reeval-kind="${esc(kind)}" data-reeval-id="${esc(id)}">
    <h3>Request re-evaluation</h3>
    <textarea name="reason" placeholder="Reason for re-evaluation" required></textarea>
    <textarea name="evidence_note" placeholder="Optional evidence note"></textarea>
    <input name="new_source_id" inputmode="numeric" placeholder="Optional new source id">
    <button type="submit">Request re-evaluation</button>
    <p class="reeval-msg notice"></p>
  </form>`;
}

function decisionForms(requests) {
  if (!currentUser || !['moderator', 'administrator'].includes(currentUser.role)) return '';
  return (requests || []).filter(request => request.status === 'open').map(request => `<form class="decision" data-request-id="${request.id}">
    <h3>Decide request #${request.id}</h3>
    <p>${esc(request.reason)}</p>
    <label>Outcome<select name="outcome"><option value="upheld">Upheld</option><option value="revised">Revised</option><option value="overturned">Overturned</option></select></label>
    <textarea name="note" placeholder="Why this outcome" required></textarea>
    <div class="revise-fields" hidden>
      <p>A revised outcome needs a new answer. The previous version is kept.</p>
      <select name="direct_answer"><option value="yes">Yes</option><option value="no">No</option><option value="gap">Gap</option></select>
      <select name="status"><option value="supported">Supported</option><option value="disputed">Disputed</option><option value="unresolved">Unresolved</option><option value="verified">Verified</option></select>
      <textarea name="facts" placeholder="Facts"></textarea>
      <textarea name="interpretation" placeholder="Interpretation"></textarea>
      <textarea name="uncertainty" placeholder="Uncertainty (optional)"></textarea>
    </div>
    <button type="submit">Record decision</button>
    <p class="decision-msg notice"></p>
  </form>`).join('');
}

function requestList(requests) {
  return (requests || []).map(request => `<article class="item"><b>Request #${request.id} · ${esc(request.status === 'open' ? 're-evaluation pending' : request.status)}</b><p>Asked by ${esc(request.requested_by_display_name || 'an unnamed person')} on ${formatWhen(request.requested_at)}. ${esc(request.reason)}</p>${request.evidence_note ? `<p>Evidence note: ${esc(request.evidence_note)}</p>` : ''}${request.winning_reason ? `<p><b>Winning evidence:</b> source #${esc(request.winning_source_id)}. ${esc(request.winning_reason)}</p>` : ''}</article>`).join('');
}

function setAuth(on) {
  $('auth').hidden = on;
  $('app').hidden = !on;
  $('logout').hidden = !on;
  if (on) refresh();
}

async function register() {
  try {
    const created = await api('/auth/register', {method: 'POST', body: JSON.stringify({email: $('email').value, display_name: $('name').value, password: $('password').value})});
    token = created.access_token;
    localStorage.setItem('epic_token', token);
    setAuth(true);
  } catch (error) {
    msg('authMsg', error.message);
  }
}

async function login() {
  try {
    const created = await api('/auth/login', {method: 'POST', body: JSON.stringify({email: $('email').value, password: $('password').value})});
    token = created.access_token;
    localStorage.setItem('epic_token', token);
    setAuth(true);
  } catch (error) {
    msg('authMsg', error.message);
  }
}

$('logout').onclick = async () => {
  try { if (token) await api('/auth/logout', {method: 'POST'}); } catch { /* local logout still proceeds */ }
  localStorage.removeItem('epic_token');
  token = null;
  currentUser = null;
  closeWorkspace();
  setAuth(false);
};

async function createDebate() {
  try {
    const debate = await api('/debates', {method: 'POST', body: JSON.stringify({
      title: $('debateTitle').value,
      fixed_question: $('question').value,
      description: $('description').value || null,
      answerability: $('debateAnswerability').value,
      answerability_reason: $('debateAnswerabilityReason').value || null,
      question_population: $('questionPopulation').value || null,
      question_timeframe: $('questionTimeframe').value || null,
      question_geography: $('questionGeography').value || null,
      question_metric: $('questionMetric').value || null,
    })});
    ['debateTitle', 'question', 'description', 'questionPopulation', 'questionTimeframe', 'questionGeography', 'questionMetric'].forEach(id => { $(id).value = ''; });
    msg('createMsg', 'Debate created.', true);
    await refresh();
    openWorkspace(debate);
  } catch (error) {
    msg('createMsg', error.message);
  }
}

async function startResearch() {
  try {
    await api('/knowledge/jobs/auto', {method: 'POST', body: JSON.stringify({query: $('researchQuery').value, dossier_id: null})});
    $('researchQuery').value = '';
    setTimeout(refresh, 100);
  } catch (error) {
    alert(error.message);
  }
}

async function refresh() {
  try {
    const [dashboard, me] = await Promise.all([api('/dashboard/summary'), api('/auth/me')]);
    currentUser = me;
    $('welcome').textContent = 'Welcome, ' + dashboard.user.display_name;
    $('counts').innerHTML = Object.entries(dashboard.counts).map(([key, value]) => `<span class="pill">${value} ${esc(key.replaceAll('_', ' '))}</span>`).join('');
    $('onboarding').hidden = dashboard.debates.length > 0;
    $('debates').innerHTML = dashboard.debates.length
      ? dashboard.debates.map(debate => `<div class="item"><b>${esc(debate.title)}</b><div>${esc(debate.fixed_question)}</div><small class="muted">${esc(debate.status)}</small><div><button type="button" data-open-debate="${debate.id}">Open workspace</button></div></div>`).join('')
      : '<p class="muted">No debates yet. Create your first debate above.</p>';
    $('jobs').innerHTML = dashboard.jobs.length
      ? dashboard.jobs.map(job => `<div class="item"><b>${esc(job.query)}</b><div class="muted">${esc(job.current_step)} · ${esc(job.status === 'not_implemented' ? 'not implemented' : job.status)}</div><div class="bar"><i style="width:${job.progress_percent}%"></i></div></div>`).join('')
      : '<p class="muted">No research jobs yet.</p>';
    refreshVerifiedClaims();
  } catch {
    localStorage.removeItem('epic_token');
    token = null;
    setAuth(false);
  }
}

async function refreshVerifiedClaims() {
  try {
    const dossiers = await api('/knowledge/dossiers');
    const cards = [];
    for (const dossier of dossiers) {
      const claims = await api(`/knowledge/dossiers/${dossier.id}/claims`);
      claims.filter(claim => claim.status === 'verified').forEach(claim => cards.push(claim));
    }
    $('verifiedClaims').innerHTML = cards.length
      ? cards.map(claim => `<article class="claim"><div class="row spread"><b>Knowledge claim #${claim.id}</b><span class="badge good">Verified</span></div><p>${esc(claim.body)}</p>${historyBlock(claim.status_history)}<p><b>Confidence:</b> ${esc(formatScore(claim.confidence_score))}</p>${claim.reevaluation_pending ? '<p>Re-evaluation pending. The request form stays closed until this request is decided.</p>' : reevaluationForm('knowledge', claim.id)}</article>`).join('')
      : '<p class="muted">No verified knowledge claims are recorded.</p>';
  } catch (error) {
    $('verifiedClaims').innerHTML = `<p class="error">${esc(error.message)}</p>`;
  }
}

function versionArticle(version, current) {
  return `<article class="item"><b>Version ${version.version_number}${current ? ' · current' : ''}</b><p>Answer: ${esc(written(ANSWERS, version.direct_answer))}</p><p>Status: ${esc(written(STATUSES, version.status))}</p><p>Outcome: ${esc(written({}, version.outcome))}</p><p><b>Facts:</b> ${esc(version.facts)}</p><p><b>Interpretation:</b> ${esc(version.interpretation)}</p><p><b>Uncertainty:</b> ${esc(blank(version.uncertainty))}</p><p>Last reviewed ${esc(String(version.last_reviewed_at).slice(0, 10))}. ${esc(version.change_log)}</p>${version.winning_reason ? `<p><b>Winning evidence:</b> source #${esc(version.winning_source_id)}. ${esc(version.winning_reason)}</p>` : ''}${confidenceList(version.confidence)}</article>`;
}

function renderEntry(entry, back = 'results') {
  const current = entry.stale ? null : entry.current_version;
  const state = entry.reevaluation_pending ? 're-evaluation pending' : (entry.stale ? 'Stale. This is not the current answer.' : (entry.needs_review ? 'Needs review' : 'Current'));
  const sources = (entry.sources || []).map(source => `<li>Source #${source.id}: ${esc(source.title)}${source.url ? ` · ${esc(source.url)}` : ''}${source.document_reference ? ` · ${esc(source.document_reference)}` : ''}</li>`).join('') || '<li>No source is linked.</li>';
  const claims = (entry.supporting_claims || []).map(claim => `<li>Claim #${claim.id}: ${esc(claim.body)}</li>`).join('') || '<li>No supporting claim is linked.</li>';
  const checks = (entry.verifications || []).map(event => `<li>Verification #${event.id}: ${esc(event.result_status)} by ${esc(event.method)}${event.mistake_reason ? ` · invalidated: ${esc(event.mistake_reason)}` : ''}</li>`).join('') || '<li>No verification event is linked.</li>';
  const history = (entry.versions || []).filter(version => !current || version.id !== current.id);
  const pending = entry.reevaluation_pending || (entry.requests || []).some(request => request.status === 'open');
  const backButton = back === 'debate'
    ? '<p><button type="button" data-library-back="debate">Back to debate</button></p>'
    : '<p><button type="button" data-library-back="results">Back to results</button></p>';
  return `<article class="claim" id="library-entry-${entry.id}">
    ${backButton}
    <div class="row spread"><b>Library entry #${entry.id}</b><span class="badge ${entry.stale || entry.reevaluation_pending || entry.needs_review ? 'warn' : 'good'}">${esc(entry.status_label || state)}</span></div>
    <p>${esc(entry.question)}</p>
    <p>Scope: population ${esc(blank(entry.question_population))}; timeframe ${esc(blank(entry.question_timeframe))}; geography ${esc(blank(entry.question_geography))}; metric ${esc(blank(entry.question_metric))}.</p>
    <p><b>${esc(state)}</b>${entry.stale ? ' The stored answer is not being served as current.' : ''}</p>
    ${current ? `<h3>Current answer</h3>${versionArticle(current, true)}` : '<p><b>Current answer:</b> none. A stale entry is not served as the current answer.</p>'}
    <h3>Linked evidence and sources</h3><ul>${claims}${sources}${checks}</ul>
    <h3>Version history</h3>${current ? `<p>Version ${current.version_number} is the current answer above and is not repeated here.</p>` : ''}${history.map(version => versionArticle(version, false)).join('') || '<p>No earlier versions.</p>'}
    ${requestList(entry.requests)}
    ${pending ? '<p>Re-evaluation pending. The request form stays closed until this request is decided.</p>' : reevaluationForm('entry', entry.id)}
    ${decisionForms(entry.requests)}
  </article>`;
}

async function openLibrary(id) {
  const entry = await api('/library/entries/' + id);
  $('libraryDetail').innerHTML = renderEntry(entry, 'results');
  $('libraryDetail').scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function openLibraryInWorkspace(id) {
  const entry = await api('/library/entries/' + id);
  $('workspaceLibrary').hidden = false;
  $('workspaceLibrary').innerHTML = renderEntry(entry, 'debate');
  $('workspaceLibrary').scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function searchLibrary() {
  try {
    const rows = await api('/library/search?q=' + encodeURIComponent($('libraryQuery').value));
    $('libraryResults').innerHTML = rows.length ? rows.map(entry => {
      const current = entry.stale ? null : entry.current_version;
      const answer = current ? `Answer: ${esc(written(ANSWERS, current.direct_answer))}. Status: ${esc(written(STATUSES, current.status))}. Last reviewed ${esc(String(current.last_reviewed_at).slice(0, 10))}.` : 'Not shown as the current answer.';
      return `<article class="item"><b>Entry #${entry.id}</b><div>${esc(entry.question)}</div><div>${answer}${entry.status_label ? ` · ${esc(entry.status_label)}` : ''}</div><button type="button" data-open-entry="${entry.id}">Open entry</button></article>`;
    }).join('') : '<p class="muted">No library entry matches.</p>';
  } catch (error) {
    $('libraryResults').innerHTML = `<p class="error">${esc(error.message)}</p>`;
  }
}

function showPanel(id) {
  for (const panel of document.querySelectorAll('#workspace .panel')) panel.hidden = panel.id !== id;
  for (const tab of document.querySelectorAll('#workspace .tab')) {
    const selected = tab.id === 'tab-' + id;
    tab.setAttribute('aria-selected', selected ? 'true' : 'false');
  }
  if (id === 'reviewPanel') refreshReviews();
  if (id === 'roomPanel') refreshRoom();
}

async function openWorkspace(debate) {
  try { currentDebate = await api('/debates/' + debate.id); } catch { currentDebate = debate; }
  $('home').hidden = true;
  $('workspace').hidden = false;
  $('workspaceTitle').textContent = currentDebate.title;
  $('workspaceQuestion').textContent = currentDebate.fixed_question;
  showPanel('claimsPanel');
  await Promise.all([refreshClaims(), refreshRoom()]);
  connectRoom();
  $('workspace').scrollIntoView({behavior: 'smooth', block: 'start'});
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function closeWorkspace() {
  currentDebate = null;
  if ($('home')) $('home').hidden = false;
  $('workspace').hidden = true;
  if (socket) { socket.close(); socket = null; }
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function renderLibraryAttachment() {
  const banner = $('libraryBanner');
  const answer = $('libraryAnswer');
  banner.hidden = true;
  answer.innerHTML = '';
  currentLibraryEntry = null;
  if (currentDebate && currentDebate.answerability === 'not_factually_answerable') {
    banner.hidden = false;
    banner.innerHTML = `<p><b>Not factually answerable.</b> This question has no factual answer. ${esc(currentDebate.answerability_reason || '')} It is not reused from the factual reference library.</p>`;
    return;
  }
  if (!currentDebate || !currentDebate.library_entry_id) {
    if (currentDebate && currentDebate.library_notice) {
      banner.hidden = false;
      banner.textContent = currentDebate.library_notice;
    }
    return;
  }
  const entry = await api('/library/entries/' + currentDebate.library_entry_id);
  currentLibraryEntry = entry;
  const stale = currentDebate.library_stale || entry.stale;
  banner.hidden = false;
  banner.innerHTML = `<p>${esc(currentDebate.library_notice || 'A library entry is attached to this debate.')}${stale ? ' This answer is not current.' : ''}</p><p><a href="#library-entry-${entry.id}" data-open-entry="${entry.id}">Open library entry #${entry.id}</a></p>`;
  if (!stale && entry.current_version) {
    const version = entry.current_version;
    const sources = (entry.sources || []).map(source => `<li>${esc(source.title)} (#${source.id})</li>`).join('') || '<li>No source is linked.</li>';
    answer.innerHTML = `<article class="claim"><h3>Attached library answer</h3><p>Answer: ${esc(written(ANSWERS, version.direct_answer))}</p><p>Status: ${esc(written(STATUSES, version.status))}</p><p>Last reviewed ${esc(String(version.last_reviewed_at).slice(0, 10))}.</p><p><b>Facts:</b> ${esc(version.facts)}</p><p><b>Interpretation:</b> ${esc(version.interpretation)}</p><p><b>Uncertainty:</b> ${esc(blank(version.uncertainty))}</p><p><b>Evidence and sources</b></p><ul>${sources}</ul>${confidenceList(version.confidence)}<p><a href="#library-entry-${entry.id}" data-open-entry="${entry.id}">Open library entry #${entry.id}</a></p></article>`;
  }
}

async function addClaim() {
  if (!currentDebate) return;
  try {
    const claim = await api(`/debates/${currentDebate.id}/claims`, {method: 'POST', body: JSON.stringify({
      body: $('claimBody').value,
      claim_type: $('claimType').value,
      uncertainty: $('claimUncertainty').value || null,
      scope_population: $('claimPopulation').value || null,
      scope_timeframe: $('claimTimeframe').value || null,
      scope_geography: $('claimGeography').value || null,
      scope_metric: $('claimMetric').value || null,
      answerability: $('claimAnswerability').value,
      answerability_reason: $('claimAnswerabilityReason').value || null,
    })});
    ['claimBody', 'claimUncertainty', 'claimPopulation', 'claimTimeframe', 'claimGeography', 'claimMetric'].forEach(id => { $(id).value = ''; });
    msg('claimMsg', (claim.needs_review ? 'Claim added and flagged for review.' : 'Claim added.') + (claim.library_notice ? ' ' + claim.library_notice : ''), !claim.needs_review);
    await refreshClaims();
  } catch (error) {
    msg('claimMsg', error.message);
  }
}

async function refreshClaims() {
  if (!currentDebate) return;
  try {
    const [claims, nodes] = await Promise.all([
      api(`/debates/${currentDebate.id}/claims`),
      api(`/debates/${currentDebate.id}/arguments`),
    ]);
    await renderLibraryAttachment();
    const libraryClaims = currentLibraryEntry?.supporting_claims || [];
    const linkedIds = new Set(libraryClaims.map(claim => claim.id));
    const verified = new Set(nodes.filter(node => node.verification_status === 'verified' && node.claim_id).map(node => node.claim_id));
    $('evidenceClaim').innerHTML = claims.length ? claims.map(claim => `<option value="${claim.id}">#${claim.id} ${esc(claim.body).slice(0, 90)}</option>`).join('') : '<option value="">Add a claim first</option>';
    const cards = await Promise.all(claims.map(async claim => {
      let summary = null;
      try { summary = await api(`/claims/${claim.id}/evidence-summary`); } catch { summary = null; }
      const links = (summary?.items || []).map(item => {
        const flags = (summary.scope_flags || []).filter(flag => flag.claim_evidence_id === item.claim_evidence_id);
        return `<article class="evidence-link"><b>Evidence link #${item.claim_evidence_id} · ${esc(item.stance)}</b><p>${esc(item.source_title || 'Source not recorded')} · tier ${esc(item.effective_tier)}</p><p>${esc(item.claim_supported)}</p><p>${scopeLine(item)}</p>${flags.length ? flagBlock(flags, '') : ''}</article>`;
      }).join('');
      return `<article class="claim"><div class="row spread"><b>Claim #${claim.id} · ${esc(claim.claim_type)}</b><span class="badge ${claim.needs_review ? 'warn' : 'good'}">${claim.needs_review ? 'Flagged for review' : 'No review flag'}</span></div><p>${esc(claim.body)}</p><p>Scope: population ${esc(blank(claim.scope_population))}; timeframe ${esc(blank(claim.scope_timeframe))}; geography ${esc(blank(claim.scope_geography))}; metric ${esc(blank(claim.scope_metric))}.</p>${claim.uncertainty ? `<p><b>Uncertainty:</b> ${esc(claim.uncertainty)}</p>` : ''}${(claim.corrections || []).map(item => `<p><b>Correction:</b> ${esc(item.original_body)} → ${esc(item.corrected_body)} (${esc(item.reason)})</p>`).join('')}${historyBlock(claim.status_notes)}<p>${esc(claim.moderation_note || 'No moderation note')}</p>${claim.library_notice ? `<p><b>Library:</b> ${esc(claim.library_notice)}</p>` : ''}${linkedIds.has(claim.id) ? `<p>Linked from library entry #${currentLibraryEntry.id}. Read-only in this record. <a href="#library-entry-${currentLibraryEntry.id}" data-open-entry="${currentLibraryEntry.id}">Open library entry #${currentLibraryEntry.id}</a></p>` : ''}${summary ? `<div class="metrics"><span>${summary.citation_count} citation(s)</span><span>Strongest tier ${esc(summary.strongest_effective_tier)}</span><span>${summary.independent_source_count} independent source(s)</span><span>${summary.citation_requirement_met ? 'Citation requirement met' : 'Citation needed'}</span></div>${confidenceBlock(summary.confidence)}${links}${flagBlock(summary.scope_flags, summary.scope_check)}` : confidenceBlock(null)}${claim.reevaluation_pending ? '<p>Re-evaluation pending. The request form stays closed until this request is decided.</p>' : (verified.has(claim.id) ? reevaluationForm('claim', claim.id) : '')}</article>`;
    }));
    const present = new Set(claims.map(claim => claim.id));
    const extras = libraryClaims.filter(claim => !present.has(claim.id)).map(claim => `<article class="claim read-only"><b>Library claim #${claim.id}</b><p>${esc(claim.body)}</p><p>Read-only. Linked from library entry #${currentLibraryEntry.id}${currentLibraryEntry.stale ? '. Not the current answer.' : ''}.</p><p><a href="#library-entry-${currentLibraryEntry.id}" data-open-entry="${currentLibraryEntry.id}">Open library entry #${currentLibraryEntry.id}</a></p></article>`).join('');
    $('claims').innerHTML = (cards.length ? cards.join('') : '<p class="muted">No claims have been added.</p>') + extras;
    const fresh = [...claims.map(claim => ({body: claim.body, status: claim.library_point_status, notice: claim.library_notice})), ...nodes.map(node => ({body: node.body, status: node.library_point_status, notice: node.library_notice}))];
    const novel = fresh.filter(point => point.status === 'new point, not yet researched');
    $('newPoints').innerHTML = novel.length
      ? `<article class="claim"><h3>New points, not yet researched</h3><ul>${novel.map(point => `<li>${esc(point.body)}. Automated research is not implemented.</li>`).join('')}</ul></article>`
      : '';
  } catch (error) {
    $('claims').innerHTML = `<p class="error">${esc(error.message)}</p>`;
  }
}

async function attachEvidence() {
  if (!currentDebate || !$('evidenceClaim').value) return;
  try {
    const scope = {
      scope_population: $('scopePopulation').value || null,
      scope_timeframe: $('scopeTimeframe').value || null,
      scope_geography: $('scopeGeography').value || null,
      scope_metric: $('scopeMetric').value || null,
      scope_study_type: $('scopeStudyType').value || null,
      scope_sample_size: $('scopeSampleSize').value ? Number($('scopeSampleSize').value) : null,
    };
    const source = await api('/sources', {method: 'POST', body: JSON.stringify({title: $('sourceTitle').value, url: $('sourceUrl').value || null, document_reference: $('documentReference').value || null, publisher: $('sourcePublisher').value || null, author: $('sourceAuthor').value || null, publication_date: null, source_type: $('sourceType').value, ...scope})});
    const citation = await api('/citations', {method: 'POST', body: JSON.stringify({source_id: source.id, locator: $('citationLocator').value || null, excerpt: $('citationExcerpt').value || null})});
    await api(`/claims/${$('evidenceClaim').value}/evidence`, {method: 'POST', body: JSON.stringify({citation_id: citation.id, stance: $('evidenceStance').value, relevance_score: 0.8, claim_supported: $('claimSupported').value, note: null, ...scope})});
    ['sourceTitle', 'sourceUrl', 'documentReference', 'sourcePublisher', 'sourceAuthor', 'citationLocator', 'citationExcerpt', 'claimSupported', 'scopePopulation', 'scopeTimeframe', 'scopeGeography', 'scopeMetric', 'scopeStudyType', 'scopeSampleSize'].forEach(id => { $(id).value = ''; });
    msg('evidenceMsg', `Evidence attached. Declared source type is ${source.source_type_reviewed ? 'reviewed' : 'unverified'}.`, true);
    await refreshClaims();
  } catch (error) {
    msg('evidenceMsg', error.message);
  }
}

async function refreshRoom() {
  if (!currentDebate) return;
  try {
    const [state, turns, participants] = await Promise.all([
      api(`/debates/${currentDebate.id}/room`),
      api(`/debates/${currentDebate.id}/turns`),
      api(`/debates/${currentDebate.id}/participants`),
    ]);
    const debaters = participants.filter(person => person.role === 'debater');
    $('turnState').textContent = state.current_participant_id
      ? `Current participant #${state.current_participant_id} · turn ${state.turn_sequence} · ${state.remaining_seconds ?? 0}s remaining`
      : 'Room waiting to be configured. Add a debater, then use Configure room.';
    $('participants').innerHTML = participants.length
      ? participants.map(person => `<div class="item">${esc(person.display_name)} · ${esc(person.role)} · ${esc(person.side)} · #${person.id}</div>`).join('')
      : '<p class="muted">No participants yet.</p>';
    $('firstDebater').innerHTML = '<option value="">First debater in the list</option>' + debaters.map(person => `<option value="${person.id}">#${person.id} ${esc(person.display_name)}</option>`).join('');
    $('turns').innerHTML = turns.length
      ? turns.map(turn => `<article class="turn"><b>Participant #${turn.participant_id}</b><small>${esc(turn.status)} · turn ${turn.sequence_number}</small><p>${esc(turn.body) || '<em>No statement</em>'}</p></article>`).join('')
      : '<p class="muted">No turns posted yet.</p>';
  } catch (error) {
    msg('roomMsg', error.message);
  }
}

async function addParticipant() {
  if (!currentDebate) return;
  try {
    await api(`/debates/${currentDebate.id}/participants`, {method: 'POST', body: JSON.stringify({display_name: $('participantName').value, role: $('participantRole').value, side: $('participantSide').value})});
    $('participantName').value = '';
    msg('roomMsg', 'Participant added.', true);
    await refreshRoom();
  } catch (error) {
    msg('roomMsg', error.message);
  }
}

async function configureRoom() {
  if (!currentDebate) return;
  try {
    await api(`/debates/${currentDebate.id}/room`, {method: 'PUT', body: JSON.stringify({turn_duration_seconds: Number($('turnSeconds').value), first_participant_id: $('firstDebater').value ? Number($('firstDebater').value) : null})});
    msg('roomMsg', 'Room configured.', true);
    await refreshRoom();
  } catch (error) {
    msg('roomMsg', error.message);
  }
}

async function previewTurn() {
  if (!currentDebate) return;
  try {
    const analysis = await api(`/debates/${currentDebate.id}/turns/preview`, {method: 'POST', body: JSON.stringify({body: $('turnBody').value})});
    msg('roomMsg', analysis.approved ? 'Preview passed: ready to submit.' : `Preview flagged: ${analysis.reasons.join(' ')}`, analysis.approved);
  } catch (error) {
    msg('roomMsg', error.message);
  }
}

async function submitTurn() {
  if (!currentDebate) return;
  try {
    await api(`/debates/${currentDebate.id}/turns`, {method: 'POST', body: JSON.stringify({body: $('turnBody').value})});
    $('turnBody').value = '';
    await refreshRoom();
  } catch (error) {
    msg('roomMsg', error.message);
  }
}

async function refreshReviews() {
  if (!currentDebate) return;
  try {
    const rows = await api(`/debates/${currentDebate.id}/moderation-reviews`);
    $('reviews').innerHTML = rows.length
      ? rows.map(review => `<article class="claim"><b>Review #${review.id}</b><p>${esc(review.body)}</p><small>${esc((review.analysis?.reasons || []).join(' ') || review.status)}</small>${review.status === 'pending' ? `<div class="row"><button type="button" onclick="decideReview(${review.id},true)">Approve</button><button type="button" class="danger" onclick="decideReview(${review.id},false)">Reject</button></div>` : ''}</article>`).join('')
      : '<p class="muted">No moderation reviews.</p>';
  } catch (error) {
    $('reviews').innerHTML = `<p class="error">${esc(error.message)}</p>`;
  }
}

async function decideReview(id, approve) {
  try {
    await api(`/moderation-reviews/${id}/decision`, {method: 'POST', body: JSON.stringify({approve, note: approve ? 'Approved in workspace' : 'Rejected in workspace'})});
    refreshReviews();
  } catch (error) {
    alert(error.message);
  }
}

async function downloadExport(kind) {
  if (!currentDebate) return;
  const path = kind === 'md' ? `/debates/${currentDebate.id}/export.md` : `/debates/${currentDebate.id}/export`;
  const response = await fetch(path, {headers: {Authorization: 'Bearer ' + token}});
  if (!response.ok) { alert('Export failed'); return; }
  const blob = await response.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `epic-debate-${currentDebate.id}.${kind}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function connectRoom() {
  if (!currentDebate || !token) return;
  if (socket) socket.close();
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${scheme}://${location.host}/ws/debates/${currentDebate.id}?token=${encodeURIComponent(token)}`);
  socket.onmessage = () => { refreshRoom(); refreshReviews(); };
  socket.onclose = () => { if (currentDebate) setTimeout(connectRoom, 2000); };
}

function showProduct(which) {
  const factual = which !== 'fable';
  $('home').hidden = !factual;
  if ($('workspace')) $('workspace').hidden = true;
  $('fablePanel').hidden = factual;
  $('tabFactual').setAttribute('aria-selected', factual ? 'true' : 'false');
  $('tabFable').setAttribute('aria-selected', factual ? 'false' : 'true');
  if (!factual) loadFables();
}

async function createFable() {
  try {
    const names = $('fableCharacters').value.split(',').map(name => name.trim()).filter(Boolean);
    const created = await api('/fable/matchups', {method: 'POST', body: JSON.stringify({title: $('fableTitle').value, question: $('fableQuestion').value, mode: $('fableMode').value, personal_knowledge_only: true, participants: names})});
    msg('fableMsg', 'Matchup created. This is fiction, not evidence.', true);
    await openFable(created.id);
  } catch (error) { msg('fableMsg', error.message); }
}

async function loadFables() {
  try {
    const rows = await api('/fable/matchups');
    $('fableList').innerHTML = rows.length ? rows.map(row => `<article class="item"><b>${esc(row.title)}</b><div>${row.mode === 'debate' ? 'Debate (personal knowledge)' : 'AI matchup'} · fiction</div><button type="button" data-open-fable="${row.id}">Open matchup</button></article>`).join('') : '<p class="muted">No fictional matchups yet.</p>';
  } catch (error) { $('fableList').innerHTML = `<p class="error">${esc(error.message)}</p>`; }
}

function fableDetail(row) {
  const lore = row.lore.map(item => `<li>#${item.id} ${esc(item.work_title)}, ${esc(item.installment)}, ${esc(item.pinpoint)} · ${esc(item.canon_status)}. ${esc(item.body)}</li>`).join('') || '<li>No lore yet.</li>';
  const steps = row.steps.map(step => `<li>Step ${step.step_number} (lore ${esc(step.lore_item_ids.join(', '))}): ${esc(step.body)}</li>`).join('') || '<li>No reasoning steps yet.</li>';
  const notes = row.canon_notes.map(note => `<li>${esc(note.kind)}: ${esc(note.note)}</li>`).join('') || '<li>None.</li>';
  const moves = row.moves.map(move => `<li>Move #${move.id}: ${esc(move.move_text)} · ${esc(move.claimed_source)} · ${esc(move.ruling || 'not ruled')}</li>`).join('') || '<li>No moves yet.</li>';
  const debate = row.mode === 'debate' ? `<h3>Moves</h3><p>There is no control to ask the AI for help. The debater supplies the feat and the citation.</p><ul>${moves}</ul><select id="fableParticipant">${row.participants.map(person => `<option value="${person.id}">${esc(person.name)}</option>`).join('')}</select><textarea id="fableMove" placeholder="Power or feat the debater claims"></textarea><input id="fableCitation" placeholder="Canon citation supplied by the debater"><button type="button" onclick="addFableMove(${row.id})">Record move</button><h3>Moderator ruling</h3><p>${esc(row.referee_scope)}</p><input id="fableMoveId" placeholder="Move id"><select id="fableRuling"><option value="allowed">Allowed</option><option value="disallowed">Disallowed</option><option value="unverified">Unverified</option></select><textarea id="fableRulingReason" placeholder="Reason for this move only"></textarea><input id="fableRulingCitation" placeholder="Citation"><button type="button" onclick="ruleFableMove()">Record moderator ruling</button><h3>Debate outcome</h3><p>Label: debate. This does not write the AI matchup outcome.</p><input id="fableDebateOutcome" placeholder="Outcome, or undetermined by canon"><textarea id="fableDebateNote" placeholder="Based only on the moves made"></textarea><input id="fableOutcomeMoves" placeholder="Ruled move ids, comma separated"><button type="button" onclick="saveDebateOutcome(${row.id})">Save debate outcome</button><p><button type="button" class="secondary" onclick="runFableReferee(${row.id})">Automated AI referee</button> Automated AI refereeing is not implemented.</p>` : `<ul>${moves}</ul><p><button type="button" class="secondary" onclick="runFableMatchup(${row.id})">Run AI matchup</button> An AI matchup run is not implemented.</p>`;
  return `<article class="claim"><p><b>Fiction.</b> ${esc(row.cheating_notice)}</p><h3>${esc(row.title)}</h3><p>${esc(row.question)}</p><p>AI matchup outcome (${esc(row.ai_outcome_label)}): ${esc(row.ai_outcome || 'none')}</p><p>Debate outcome (${esc(row.debate_outcome_label)}): ${esc(row.debate_outcome || 'none')}</p><p>Automated analysis: ${esc(row.automated_analysis)}. Automated referee: ${esc(row.automated_referee)}.</p><h3>Lore</h3><ul>${lore}</ul><input id="loreWork" placeholder="Work title"><input id="loreInstallment" placeholder="Issue, episode, or film"><input id="lorePin" placeholder="Page or timestamp"><select id="loreCanon"><option value="primary_canon">Primary canon</option><option value="secondary">Secondary</option><option value="non_canon">Non-canon</option></select><textarea id="loreBody" placeholder="What the cited lore says"></textarea><button type="button" onclick="addFableLore(${row.id})">Add lore</button><h3>Reasoning</h3><ul>${steps}</ul><input id="stepNumber" type="number" min="1" value="1"><textarea id="stepBody" placeholder="Reasoning using only cited lore"></textarea><input id="stepLore" placeholder="Lore item ids"><button type="button" onclick="addFableStep(${row.id})">Add step</button><h3>Canon notes</h3><ul>${notes}</ul><select id="canonKind"><option value="silent">Canon is silent</option><option value="contradicts">Canon contradicts itself</option></select><textarea id="canonNote" placeholder="Note"></textarea><button type="button" onclick="addFableNote(${row.id})">Add canon note</button>${debate}<p id="fableDetailMsg" class="notice"></p></article>`;
}

async function openFable(id) {
  const row = await api('/fable/matchups/' + id);
  $('fableDetail').innerHTML = fableDetail(row);
  await loadFables();
}
async function loadFables() {
  const rows = await api('/fable/matchups');
  $('fableList').innerHTML = rows.length ? rows.map(row => `<article class="item"><b>${esc(row.title)}</b><div>${row.mode === 'debate' ? 'Debate (personal knowledge)' : 'AI matchup'} · fiction</div><button type="button" data-open-fable="${row.id}">Open matchup</button></article>`).join('') : '<p class="muted">No fictional matchups yet.</p>';
}
async function addFableLore(id) { try { await api(`/fable/matchups/${id}/lore`, {method:'POST', body: JSON.stringify({work_title:$('loreWork').value, installment:$('loreInstallment').value, pinpoint:$('lorePin').value, canon_status:$('loreCanon').value, body:$('loreBody').value})}); await openFable(id); } catch (error) { msg('fableDetailMsg', error.message); } }
async function addFableStep(id) { try { const lore = $('stepLore').value.split(',').map(value => Number(value.trim())).filter(Boolean); await api(`/fable/matchups/${id}/steps`, {method:'POST', body: JSON.stringify({step_number:Number($('stepNumber').value), body:$('stepBody').value, lore_item_ids:lore})}); await openFable(id); } catch (error) { msg('fableDetailMsg', error.message); } }
async function addFableNote(id) { try { await api(`/fable/matchups/${id}/canon-notes`, {method:'POST', body: JSON.stringify({kind:$('canonKind').value, note:$('canonNote').value})}); await openFable(id); } catch (error) { msg('fableDetailMsg', error.message); } }
async function addFableMove(id) { try { await api(`/fable/matchups/${id}/moves`, {method:'POST', body: JSON.stringify({participant_id:Number($('fableParticipant').value), move_text:$('fableMove').value, claimed_source:$('fableCitation').value})}); await openFable(id); } catch (error) { msg('fableDetailMsg', error.message); } }
async function ruleFableMove() { try { const move = await api(`/fable/moves/${$('fableMoveId').value}/ruling`, {method:'POST', body: JSON.stringify({ruling:$('fableRuling').value, reason:$('fableRulingReason').value, citation:$('fableRulingCitation').value})}); await openFable(move.matchup_id); } catch (error) { msg('fableDetailMsg', error.message); } }
async function saveDebateOutcome(id) { try { const moveIds = $('fableOutcomeMoves').value.split(',').map(value => Number(value.trim())).filter(Boolean); await api(`/fable/matchups/${id}/debate-outcome`, {method:'POST', body: JSON.stringify({outcome:$('fableDebateOutcome').value, note:$('fableDebateNote').value, move_ids:moveIds})}); await openFable(id); } catch (error) { msg('fableDetailMsg', error.message); } }
async function runFableMatchup(id) { try { const result = await api(`/fable/matchups/${id}/automated-run`, {method:'POST'}); msg('fableDetailMsg', result.detail); await openFable(id); } catch (error) { msg('fableDetailMsg', error.message); } }
async function runFableReferee(id) { try { const result = await api(`/fable/matchups/${id}/automated-referee`, {method:'POST'}); msg('fableDetailMsg', result.detail); await openFable(id); } catch (error) { msg('fableDetailMsg', error.message); } }

document.body.addEventListener('click', event => {
  const fableButton = event.target.closest('[data-open-fable]');
  if (fableButton) openFable(Number(fableButton.dataset.openFable));
  const debateButton = event.target.closest('[data-open-debate]');
  if (debateButton) openWorkspace({id: Number(debateButton.dataset.openDebate)});
  const entryButton = event.target.closest('[data-open-entry]');
  if (entryButton) {
    event.preventDefault();
    const entryId = Number(entryButton.dataset.openEntry);
    if (!$('workspace').hidden) openLibraryInWorkspace(entryId);
    else openLibrary(entryId);
  }
  if (event.target.closest('[data-library-back="results"]')) $('libraryResults').scrollIntoView({behavior: 'smooth', block: 'start'});
  if (event.target.closest('[data-library-back="debate"]')) {
    $('workspaceLibrary').hidden = true;
    $('workspaceLibrary').innerHTML = '';
    $('claimsPanel').scrollIntoView({behavior: 'smooth', block: 'start'});
  }
});

document.body.addEventListener('change', event => {
  if (event.target.name === 'outcome' && event.target.form?.classList.contains('decision')) {
    event.target.form.querySelector('.revise-fields').hidden = event.target.value !== 'revised';
  }
});

document.body.addEventListener('submit', async event => {
  const form = event.target;
  if (form.classList.contains('reeval')) {
    event.preventDefault();
    const data = new FormData(form);
    const sourceId = String(data.get('new_source_id') || '').trim();
    const body = {reason: data.get('reason'), evidence_note: data.get('evidence_note') || null, new_source_id: sourceId ? Number(sourceId) : null};
    const kind = form.dataset.reevalKind;
    const id = form.dataset.reevalId;
    const path = kind === 'entry' ? `/library/entries/${id}/reevaluations` : '/library/reevaluations';
    if (kind === 'knowledge') body.knowledge_claim_id = Number(id);
    if (kind === 'claim') body.claim_id = Number(id);
    try {
      await api(path, {method: 'POST', body: JSON.stringify(body)});
      form.querySelector('.reeval-msg').textContent = 'Re-evaluation requested. The entry shows re-evaluation pending while it is open.';
      form.querySelector('.reeval-msg').className = 'reeval-msg notice ok';
      if (kind === 'entry') openLibrary(id);
      if (kind === 'knowledge') refreshVerifiedClaims();
      if (kind === 'claim') refreshClaims();
    } catch (error) {
      form.querySelector('.reeval-msg').textContent = error.message;
      form.querySelector('.reeval-msg').className = 'reeval-msg notice error';
    }
  }
  if (form.classList.contains('decision')) {
    event.preventDefault();
    const data = new FormData(form);
    const outcome = data.get('outcome');
    const body = {outcome, note: data.get('note')};
    if (outcome === 'revised') {
      body.direct_answer = data.get('direct_answer');
      body.status = data.get('status');
      body.facts = data.get('facts');
      body.interpretation = data.get('interpretation');
      body.uncertainty = data.get('uncertainty') || null;
    }
    try {
      const decided = await api(`/library/reevaluations/${form.dataset.requestId}/decision`, {method: 'POST', body: JSON.stringify(body)});
      form.querySelector('.decision-msg').textContent = `Recorded ${decided.status}. ${decided.winning_reason || ''}`;
      form.querySelector('.decision-msg').className = 'decision-msg notice ok';
      if (decided.entry_id) openLibrary(decided.entry_id);
    } catch (error) {
      form.querySelector('.decision-msg').textContent = error.message;
      form.querySelector('.decision-msg').className = 'decision-msg notice error';
    }
  }
});

if (token) setAuth(true);
setInterval(() => { if (token && $('home') && !$('home').hidden) refresh(); if (currentDebate) refreshRoom(); }, 3000);
