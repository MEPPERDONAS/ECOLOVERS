const LABELS = ['Cartón', 'Vidrio', 'Metal', 'Papel', 'Plástico', 'Basura General'];
const CAT_ICONS = ['📦', '🍶', '🔩', '📄', '🧴', '🗑️'];
const GUIDE_SLUGS = ['carton', 'vidrio', 'metal', 'papel', 'plastico', 'basura-general'];

let imageQueue = [];
let analyzing = false;
let cameraStream = null;

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

const cameraDock = document.getElementById('camera-dock');
const openCameraDockBtn = document.getElementById('open-camera-dock');
const closeCameraDockBtn = document.getElementById('close-camera-dock');
const videoEl = document.getElementById('camera-video');
const canvasEl = document.getElementById('camera-canvas');
const btnCapture = document.getElementById('btn-capture');
const switchCameraBtn = document.getElementById('switch-camera');
let currentFacingMode = 'environment';

if (dropZone && fileInput) {
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
}

if (openCameraDockBtn) {
  openCameraDockBtn.addEventListener('click', openCameraDock);
}
if (closeCameraDockBtn) {
  closeCameraDockBtn.addEventListener('click', closeCameraDock);
}
if (btnCapture) {
  btnCapture.addEventListener('click', captureAndAnalyze);
}

async function openCameraDock() {
  if (!cameraDock) return;
  cameraDock.hidden = false;
  currentFacingMode = 'environment';
  await startCamera();
}

function closeCameraDock() {
  if (cameraDock) cameraDock.hidden = true;
  stopCamera();
}

async function startCamera() {
  if (!videoEl || !btnCapture) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert('Tu navegador no soporta acceso a la camara.');
    return;
  }

  stopCamera();

  try {
    const constraints = {
      audio: false,
      video: {
        facingMode: { ideal: currentFacingMode }
      }
    };

    cameraStream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch (e) {
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    } catch (innerError) {
      console.error(innerError);
      alert('No se pudo abrir la camara. Revisa permisos del navegador.');
      return;
    }
  }

  videoEl.srcObject = cameraStream;
  btnCapture.disabled = false;
  await updateSwitchCameraState();
}

async function switchCamera() {
  currentFacingMode = currentFacingMode === 'environment' ? 'user' : 'environment';
  await startCamera();
}

async function updateSwitchCameraState() {
  if (!switchCameraBtn || !navigator.mediaDevices?.enumerateDevices) return;

  let videoInputs = [];
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    videoInputs = devices.filter(d => d.kind === 'videoinput');
  } catch (_err) {
    videoInputs = [];
  }

  const canSwitch = videoInputs.length > 1;
  switchCameraBtn.disabled = !canSwitch;

  const current = currentFacingMode === 'environment' ? 'trasera' : 'frontal';
  switchCameraBtn.textContent = canSwitch ? `Camara: ${current}` : 'Una camara';
}

function stopCamera() {
  if (!cameraStream) return;
  cameraStream.getTracks().forEach(track => track.stop());
  cameraStream = null;
  if (videoEl) videoEl.srcObject = null;
  if (btnCapture) btnCapture.disabled = true;
}

async function captureAndAnalyze() {
  if (!cameraStream || !videoEl || !canvasEl) return;

  const width = videoEl.videoWidth;
  const height = videoEl.videoHeight;
  if (!width || !height) return;

  canvasEl.width = width;
  canvasEl.height = height;
  const ctx = canvasEl.getContext('2d');
  ctx.drawImage(videoEl, 0, 0, width, height);

  canvasEl.toBlob(async blob => {
    if (!blob) return;

    const file = new File([blob], `captura_${Date.now()}.png`, { type: 'image/png' });
    addFiles([file]);

    const lastItem = imageQueue[imageQueue.length - 1];
    if (!lastItem) return;

    try {
      showAnalyzingOverlay(lastItem.id);
      lastItem.result = await classifyImage(lastItem);
      removeAnalyzingOverlay(lastItem.id);
      updateCard(lastItem);
      showSummary();
      closeCameraDock();
    } catch (error) {
      removeAnalyzingOverlay(lastItem.id);
      console.error(error);
      alert('No se pudo analizar la foto capturada.');
    }
  }, 'image/png');
}

window.addEventListener('beforeunload', stopCamera);

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
  if (!grid) return;

  const card = document.createElement('div');
  card.className = 'image-card';
  card.id = `card-${item.id}`;
  card.innerHTML = `
    <img src="${item.url}" alt="${item.name}">
    <div class="image-card-info">
      <div class="image-name">${item.name}</div>
      <div class="image-result" id="result-${item.id}">-</div>
      <div class="image-confidence" id="conf-${item.id}"></div>
      <div class="confidence-bar">
        <div class="confidence-fill" id="bar-${item.id}" style="width:0%"></div>
      </div>
    </div>
    <button class="remove-btn" onclick="removeItem('${item.id}')">x</button>
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
  const grid = document.getElementById('image-grid');
  const summary = document.getElementById('summary');
  const exportArea = document.getElementById('export-area');
  if (grid) grid.innerHTML = '';
  if (summary) summary.style.display = 'none';
  if (exportArea) exportArea.style.display = 'none';
  updateUI();
}

function updateUI() {
  const count = imageQueue.length;
  const batchHeader = document.getElementById('batch-header');
  const countEl = document.getElementById('img-count');
  const analyzeArea = document.getElementById('analyze-area');

  if (batchHeader) batchHeader.style.display = count > 0 ? 'flex' : 'none';
  if (countEl) countEl.textContent = count;
  if (analyzeArea) analyzeArea.style.display = count > 0 ? 'flex' : 'none';
}

async function analyzeAll() {
  if (analyzing || imageQueue.length === 0) return;
  analyzing = true;

  const pending = imageQueue.filter(i => i.result === null);
  if (!pending.length) {
    analyzing = false;
    return;
  }

  const analyzeBtn = document.getElementById('btn-analyze');
  const progressWrap = document.getElementById('progress-wrap');
  if (analyzeBtn) analyzeBtn.disabled = true;
  if (progressWrap) progressWrap.style.display = 'block';

  for (let i = 0; i < pending.length; i++) {
    const item = pending[i];
    updateProgress(i, pending.length, item.name);
    showAnalyzingOverlay(item.id);

    try {
      item.result = await classifyImage(item);
    } catch (e) {
      console.error(e);
      item.result = { label: 'Error', confidence: 0, catIndex: -1, slug: '' };
    }

    removeAnalyzingOverlay(item.id);
    updateCard(item);
    updateProgress(i + 1, pending.length, '');
  }

  if (analyzeBtn) analyzeBtn.disabled = false;
  if (progressWrap) progressWrap.style.display = 'none';
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
    label: data.label,
    slug: data.slug || GUIDE_SLUGS[LABELS.indexOf(data.label)] || '',
    confidence: data.confidence,
    catIndex: LABELS.indexOf(data.label),
    allScores: data.all_scores || []
  };
}

function updateCard(item) {
  const { label, slug, confidence, catIndex } = item.result;
  document.getElementById(`card-${item.id}`)?.classList.add('analyzed');

  const resultEl = document.getElementById(`result-${item.id}`);
  const confEl = document.getElementById(`conf-${item.id}`);
  const barEl = document.getElementById(`bar-${item.id}`);

  if (resultEl) {
    resultEl.innerHTML = `<a href="/guia/${slug}" class="result-link">${CAT_ICONS[catIndex] ?? '?'} ${label}</a>`;
    resultEl.className = `image-result cat-${catIndex}`;
  }
  if (confEl) confEl.textContent = `${confidence}% confianza`;
  if (barEl) setTimeout(() => { barEl.style.width = `${confidence}%`; }, 100);
}

function showAnalyzingOverlay(id) {
  const card = document.getElementById(`card-${id}`);
  if (!card) return;
  const overlay = document.createElement('div');
  overlay.className = 'analyzing-overlay';
  overlay.id = `overlay-${id}`;
  overlay.innerHTML = '<div class="spinner"></div><div class="spinner-label">Analizando</div>';
  card.appendChild(overlay);
}

function removeAnalyzingOverlay(id) {
  document.getElementById(`overlay-${id}`)?.remove();
}

function updateProgress(current, total, filename) {
  const pct = Math.round((current / total) * 100);
  const fill = document.getElementById('progress-fill');
  const pctEl = document.getElementById('progress-pct');
  const text = document.getElementById('progress-text');
  if (fill) fill.style.width = `${pct}%`;
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (text) text.textContent = current < total ? `Analizando: ${filename}` : 'Completado';
}

function showSummary() {
  const counts = Object.fromEntries(LABELS.map(label => [label, 0]));
  imageQueue
    .filter(i => i.result && i.result.label !== 'Error')
    .forEach(i => counts[i.result.label]++);

  const grid = document.getElementById('summary-grid');
  if (!grid) return;

  grid.innerHTML = '';

  LABELS.forEach((label, idx) => {
    if (!counts[label]) return;
    const slug = GUIDE_SLUGS[idx];
    const el = document.createElement('div');
    el.className = 'summary-item';
    el.innerHTML = `
      <a href="/guia/${slug}" class="summary-link">
        <div class="summary-count cat-${idx}">${counts[label]}</div>
        <div style="font-size:1.5rem">${CAT_ICONS[idx]}</div>
        <div class="summary-label">${label}</div>
      </a>
    `;
    grid.appendChild(el);
  });

  const summary = document.getElementById('summary');
  const exportArea = document.getElementById('export-area');
  if (summary) summary.style.display = 'block';
  if (exportArea) exportArea.style.display = 'flex';
}

function exportCSV() {
  const rows = [['Archivo', 'Clasificacion', 'Confianza (%)']];
  imageQueue.filter(i => i.result).forEach(i => rows.push([i.name, i.result.label, i.result.confidence]));
  download('resultados_clasificacion.csv', rows.map(r => r.join(',')).join('\n'), 'text/csv');
}

function exportJSON() {
  const data = imageQueue.filter(i => i.result).map(i => ({
    archivo: i.name,
    clasificacion: i.result.label,
    confianza: i.result.confidence
  }));
  download('resultados_clasificacion.json', JSON.stringify(data, null, 2), 'application/json');
}

function download(filename, content, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = filename;
  a.click();
}



