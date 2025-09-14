// Basic single-page upload + result rendering logic (supports file OR URL)
const form = document.getElementById('uploadForm');
const statusEl = document.getElementById('status');
const resultSection = document.getElementById('resultSection');
const metaPre = document.getElementById('metaPre');
const fieldsTableBody = document.querySelector('#fieldsTable tbody');
const extraTableBody = document.querySelector('#extraTable tbody');
const rawJson = document.getElementById('rawJson');
const missingWrap = document.getElementById('missingWrap');
const missingList = document.getElementById('missingList');
const submitBtn = document.getElementById('submitBtn');
const fileGroup = document.getElementById('fileGroup');
const urlGroup = document.getElementById('urlGroup');
const sourceUrlInput = document.getElementById('sourceUrl');
const sourceModeRadios = document.querySelectorAll('input[name="sourceMode"]');
const extractModeRadios = document.querySelectorAll('input[name="extractMode"]');
const multiDocsContainer = document.getElementById('multiDocsContainer');
const multiDocsList = document.getElementById('multiDocsList');
// Toggle single vs multi result display reset
extractModeRadios.forEach(r => {
  r.addEventListener('change', () => {
    resultSection.classList.add('hidden');
    rawJson.textContent='';
    multiDocsList.innerHTML='';
    multiDocsContainer.classList.add('hidden');
    setStatus('', 'info');
  });
});

function getExtractMode(){
  const checked = document.querySelector('input[name="extractMode"]:checked');
  return checked ? checked.value : 'single';
}

// Toggle visibility between file and URL inputs
sourceModeRadios.forEach(r => {
  r.addEventListener('change', () => {
    const mode = getMode();
    if(mode === 'file') {
      fileGroup.classList.remove('hidden');
      urlGroup.classList.add('hidden');
      sourceUrlInput.value = '';
    } else {
      urlGroup.classList.remove('hidden');
      fileGroup.classList.add('hidden');
      document.getElementById('fileInput').value = '';
    }
    setStatus('', 'info');
    resultSection.classList.add('hidden');
  });
});

function getMode(){
  const checked = document.querySelector('input[name="sourceMode"]:checked');
  return checked ? checked.value : 'file';
}

function setStatus(msg, type='info') { // Update UI status banner
  statusEl.textContent = msg;
  statusEl.className = 'status ' + type;
}

function rowHTML(k, vObj) { // Table row for field (supports string or object)
  let value, conf;
  if (vObj && typeof vObj === 'object' && 'value' in vObj) {
    value = vObj.value ?? '';
    conf = (vObj.confidence != null) ? Number(vObj.confidence).toFixed(2) : '';
  } else {
    value = (vObj == null) ? '' : String(vObj);
    conf = '';
  }
  return `<tr><td>${k}</td><td>${escapeHtml(value)}</td><td>${conf || ''}</td></tr>`;
}

function escapeHtml(str){ // Prevent HTML injection in values
  return str.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
}

form.addEventListener('submit', async (e) => { // Handle form submission
  e.preventDefault();
  const mode = getMode();
  const extractMode = getExtractMode();
  const docType = document.getElementById('docType').value.trim();
  const fd = new FormData();
  if(docType) fd.append('doc_type', docType);
  if(mode === 'file') {
    const file = document.getElementById('fileInput').files[0];
    if(!file){
      setStatus('Select a file first','warn');
      return;
    }
    fd.append('file', file);
  } else {
    const url = sourceUrlInput.value.trim();
    if(!url){
      setStatus('Enter a source URL','warn');
      return;
    }
    fd.append('source_url', url);
  }
  submitBtn.disabled = true;
  setStatus('Submitting & extracting...','info');
  resultSection.classList.add('hidden');
  try {
  const endpoint = extractMode === 'multi' ? '/extract/vision/multi' : '/extract/vision/single';
  const resp = await fetch(endpoint, { method:'POST', body: fd });
    const text = await resp.text();
    let json;
    try { json = JSON.parse(text); } catch(_){ throw new Error('Invalid JSON response'); }
    if(!resp.ok){
      const detail = json?.error?.detail || json?.detail || 'Unexpected error';
      throw new Error(detail);
    }
    if(extractMode === 'multi') {
      populateMultiResult(json);
    } else {
      populateResult(json);
    }
    setStatus('Success','success');
  } catch(err){
    console.error(err);
    setStatus('Error: '+ err.message,'error');
  } finally {
    submitBtn.disabled = false;
  }
});

function populateResult(data){ // Fill tables from simplified API response
  resultSection.classList.remove('hidden');
  multiDocsContainer.classList.add('hidden');
  // Derive lightweight meta summary instead of old meta structure
  const summary = {
    doc_type: data.doc_type || null,
    fields_count: data.fields ? Object.keys(data.fields).length : 0,
    extra_fields_count: data.extra_fields ? Object.keys(data.extra_fields).length : 0,
    confidence_included: !!data.fields_confidence
  };
  metaPre.textContent = JSON.stringify(summary, null, 2);

  // If confidence maps present, merge them temporarily for display
  let displayFields = {};
  let displayExtra = {};
  if (data.fields_confidence) {
    for (const k in data.fields) {
      displayFields[k] = { value: data.fields[k], confidence: data.fields_confidence[k] };
    }
  } else {
    // Convert plain strings to value objects so rowHTML shows them consistently
    for (const k in (data.fields||{})) {
      const val = data.fields[k];
      displayFields[k] = typeof val === 'object' ? val : { value: val };
    }
  }
  if (data.extra_fields_confidence) {
    for (const k in data.extra_fields) {
      displayExtra[k] = { value: data.extra_fields[k], confidence: data.extra_fields_confidence[k] };
    }
  } else {
    for (const k in (data.extra_fields||{})) {
      const val = data.extra_fields[k];
      displayExtra[k] = typeof val === 'object' ? val : { value: val };
    }
  }

  rawJson.textContent = JSON.stringify(data, null, 2);
  fieldsTableBody.innerHTML = Object.entries(displayFields).map(([k,v])=>rowHTML(k,v)).join('') || '<tr><td colspan="3">(none)</td></tr>';
  extraTableBody.innerHTML = Object.entries(displayExtra).map(([k,v])=>rowHTML(k,v)).join('') || '<tr><td colspan="3">(none)</td></tr>';

  // Hide missing section permanently (feature removed)
  missingWrap.classList.add('hidden');
  missingList.innerHTML = '';
}

function populateMultiResult(data){
  resultSection.classList.remove('hidden');
  multiDocsContainer.classList.remove('hidden');
  // Basic meta
  const summary = {
    total_groups: data.documents ? data.documents.length : 0,
    total_pages: data.meta ? data.meta.total_pages : null,
    elapsed_ms: data.meta ? data.meta.elapsed_ms : null
  };
  metaPre.textContent = JSON.stringify(summary, null, 2);
  rawJson.textContent = JSON.stringify(data, null, 2);
  // Clear single tables (not applicable for multi) but keep structure
  fieldsTableBody.innerHTML = '<tr><td colspan="3">(multi mode - see groups below)</td></tr>';
  extraTableBody.innerHTML = '<tr><td colspan="3">(multi mode - see groups below)</td></tr>';
  // Render groups
  multiDocsList.innerHTML = (data.documents || []).map(doc => {
    const fRows = Object.entries(doc.merged_fields || {}).map(([k,v])=>`<tr><td>${k}</td><td>${escapeHtml(String(v))}</td></tr>`).join('') || '<tr><td colspan="2">(none)</td></tr>';
    const xRows = Object.entries(doc.merged_extra_fields || {}).map(([k,v])=>`<tr><td>${k}</td><td>${escapeHtml(String(v))}</td></tr>`).join('') || '<tr><td colspan="2">(none)</td></tr>';
    return `<div class="multi-doc-card">
      <h4>Group ${doc.group_id} ${doc.doc_type ? '('+escapeHtml(doc.doc_type)+')' : ''}</h4>
      <div class="multi-meta">Pages: [${(doc.page_indices||[]).join(', ')}]</div>
      <details><summary>Fields (${Object.keys(doc.merged_fields||{}).length})</summary>
        <table class="mini"><tbody>${fRows}</tbody></table>
      </details>
      <details><summary>Extra Fields (${Object.keys(doc.merged_extra_fields||{}).length})</summary>
        <table class="mini"><tbody>${xRows}</tbody></table>
      </details>
      <details><summary>Representative Raw</summary>
        <pre>${escapeHtml(JSON.stringify(doc.representative, null, 2))}</pre>
      </details>
    </div>`;
  }).join('');
  missingWrap.classList.add('hidden');
  missingList.innerHTML='';
}
