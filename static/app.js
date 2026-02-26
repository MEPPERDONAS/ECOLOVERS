const LABELS = ['Cartón', 'Vidrio', 'Metal', 'Papel', 'Plástico', 'Basura General'];
const CAT_ICONS = ['📦', '🍶', '🔩', '📄', '🧴', '🗑️'];

// Estado en memoria
let imageQueue = [];
let analyzing = false;

// CÃ¡mara
const videoEl = document.getElementById('camera-video');
const canvasEl = document.getElementById('camera-canvas');
const btnCapture = document.getElementById('btn-capture');
const btnStopCamera = document.getElementById('btn-stop-camera');
let cameraStream = null;

// ── Drag & Drop ────────────────────────────────────────────
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  addFiles([...e.dataTransfer.files]);
});
dropZone.addEventListener('click', e => {
  if (e.target.tagName !== 'SPAN') fileInput.click();
});
fileInput.addEventListener('change', () => addFiles([...fileInput.files]));

// â”€â”€ CÃ¡mara â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function startCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert('Tu navegador no soporta acceso a la cÃ¡mara.');
    return;
  }
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    videoEl.srcObject = cameraStream;
    btnCapture.disabled = false;
    btnStopCamera.disabled = false;
  } catch (e) {
    console.error(e);
    alert('No se pudo abrir la cÃ¡mara. Revisa los permisos del navegador.');
  }
}

function stopCamera() {
  if (!cameraStream) return;
  cameraStream.getTracks().forEach(t => t.stop());
  cameraStream = null;
  if (videoEl) videoEl.srcObject = null;
  btnCapture.disabled = true;
  btnStopCamera.disabled = true;
}

function capturePhoto() {
  if (!cameraStream || !videoEl) return;
  const w = videoEl.videoWidth;
  const h = videoEl.videoHeight;
  if (!w || !h) return;

  canvasEl.width = w;
  canvasEl.height = h;
  const ctx = canvasEl.getContext('2d');
  ctx.drawImage(videoEl, 0, 0, w, h);

  canvasEl.toBlob(blob => {
    if (!blob) return;
    const filename = `captura_${Date.now()}.png`;
    const file = new File([blob], filename, { type: 'image/png' });
    addFiles([file]);
  }, 'image/png');
}

window.addEventListener('beforeunload', stopCamera);

// ── Agregar imágenes ───────────────────────────────────────
function addFiles(files) {
  const valid = files.filter(f => f.type.startsWith('image/'));
  valid.forEach(file => {
    const url = URL.createObjectURL(file);
    const item = { id: Date.now() + Math.random(), file, name: file.name, url, result: null };
    imageQueue.push(item);
    renderCard(item);
  });
  updateUI();
}

function renderCard(item) {
  const grid = document.getElementById('image-grid');
  const card = document.createElement('div');
  card.className = 'image-card';
  card.id = `card-${item.id}`;
  card.innerHTML = `
    <img src="${item.url}" alt="${item.name}">
    <div class="image-card-info">
      <div class="image-name">${item.name}</div>
      <div class="image-result" id="result-${item.id}">—</div>
      <div class="image-confidence" id="conf-${item.id}"></div>
      <div class="confidence-bar">
        <div class="confidence-fill" id="bar-${item.id}" style="width:0%"></div>
      </div>
    </div>
    <button class="remove-btn" onclick="removeItem('${item.id}')">✕</button>
  `;
  grid.appendChild(card);
}

function removeItem(id) {
  imageQueue = imageQueue.filter(i => String(i.id) !== String(id));
  document.getElementById(`card-${id}`)?.remove();
  updateUI();
}

function clearAll() {
  imageQueue = [];
  document.getElementById('image-grid').innerHTML = '';
  document.getElementById('summary').style.display = 'none';
  document.getElementById('export-area').style.display = 'none';
  updateUI();
}

function updateUI() {
  const count = imageQueue.length;
  document.getElementById('batch-header').style.display = count > 0 ? 'flex' : 'none';
  document.getElementById('img-count').textContent = count;
  document.getElementById('analyze-area').style.display = count > 0 ? 'flex' : 'none';
}

// ── Análisis ───────────────────────────────────────────────
async function analyzeAll() {
  if (analyzing || imageQueue.length === 0) return;
  analyzing = true;

  const pending = imageQueue.filter(i => i.result === null);
  if (!pending.length) { analyzing = false; return; }

  document.getElementById('btn-analyze').disabled = true;
  document.getElementById('progress-wrap').style.display = 'block';

  for (let i = 0; i < pending.length; i++) {
    const item = pending[i];
    updateProgress(i, pending.length, item.name);
    showAnalyzingOverlay(item.id);

    try {
      item.result = await classifyImage(item);
    } catch (e) {
      console.error(e);
      item.result = { label: 'Error', confidence: 0, catIndex: -1 };
    }

    removeAnalyzingOverlay(item.id);
    updateCard(item);
    updateProgress(i + 1, pending.length, '');
  }

  document.getElementById('btn-analyze').disabled = false;
  document.getElementById('progress-wrap').style.display = 'none';
  showSummary();
  analyzing = false;
}

async function classifyImage(item) {
  const formData = new FormData();
  formData.append('image', item.file);

  const res = await fetch('/predict', { method: 'POST', body: formData });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }

  const data = await res.json();
  return {
    label:      data.label,
    confidence: data.confidence,
    catIndex:   LABELS.indexOf(data.label),
    allScores:  data.all_scores || []
  };
}

// ── UI helpers ─────────────────────────────────────────────
function updateCard(item) {
  const { label, confidence, catIndex } = item.result;
  document.getElementById(`card-${item.id}`)?.classList.add('analyzed');

  const resultEl = document.getElementById(`result-${item.id}`);
  const confEl   = document.getElementById(`conf-${item.id}`);
  const barEl    = document.getElementById(`bar-${item.id}`);

  if (resultEl) {
    resultEl.textContent = `${CAT_ICONS[catIndex] ?? '?'} ${label}`;
    resultEl.className   = `image-result cat-${catIndex}`;
  }
  if (confEl) confEl.textContent = `${confidence}% confianza`;
  if (barEl)  setTimeout(() => { barEl.style.width = confidence + '%'; }, 100);
}

function showAnalyzingOverlay(id) {
  const card = document.getElementById(`card-${id}`);
  if (!card) return;
  const overlay = document.createElement('div');
  overlay.className = 'analyzing-overlay';
  overlay.id = `overlay-${id}`;
  overlay.innerHTML = `<div class="spinner"></div><div class="spinner-label">Analizando</div>`;
  card.appendChild(overlay);
}

function removeAnalyzingOverlay(id) {
  document.getElementById(`overlay-${id}`)?.remove();
}

function updateProgress(current, total, filename) {
  const pct = Math.round((current / total) * 100);
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('progress-pct').textContent  = pct + '%';
  document.getElementById('progress-text').textContent =
    current < total ? `Analizando: ${filename}` : '✓ Completado';
}

function showSummary() {
  const counts = Object.fromEntries(LABELS.map(l => [l, 0]));
  imageQueue
    .filter(i => i.result && i.result.label !== 'Error')
    .forEach(i => counts[i.result.label]++);

  const grid = document.getElementById('summary-grid');
  grid.innerHTML = '';

  LABELS.forEach((label, idx) => {
    if (!counts[label]) return;
    const el = document.createElement('div');
    el.className = 'summary-item';
    el.innerHTML = `
      <div class="summary-count cat-${idx}">${counts[label]}</div>
      <div style="font-size:1.5rem">${CAT_ICONS[idx]}</div>
      <div class="summary-label">${label}</div>
    `;
    grid.appendChild(el);
  });

  document.getElementById('summary').style.display      = 'block';
  document.getElementById('export-area').style.display  = 'flex';
}

// ── Exportar ───────────────────────────────────────────────
function exportCSV() {
  const rows = [['Archivo', 'Clasificación', 'Confianza (%)']];
  imageQueue.filter(i => i.result).forEach(i =>
    rows.push([i.name, i.result.label, i.result.confidence])
  );
  download('resultados_clasificacion.csv', rows.map(r => r.join(',')).join('\n'), 'text/csv');
}

function exportJSON() {
  const data = imageQueue.filter(i => i.result).map(i => ({
    archivo:        i.name,
    clasificacion:  i.result.label,
    confianza:      i.result.confidence
  }));
  download('resultados_clasificacion.json', JSON.stringify(data, null, 2), 'application/json');
}

function download(filename, content, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = filename;
  a.click();
}
