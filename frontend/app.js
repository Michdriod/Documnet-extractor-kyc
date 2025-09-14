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
  const resp = await fetch(`/extract/vision/single`, { method:'POST', body: fd });
    const text = await resp.text();
    let json;
    try { json = JSON.parse(text); } catch(_){ throw new Error('Invalid JSON response'); }
    if(!resp.ok){
      const detail = json?.error?.detail || json?.detail || 'Unexpected error';
      throw new Error(detail);
    }
    populateResult(json);
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
