/* App Main — Wire everything together */

let currentAnalysisFileId = null;

function openAnalysis(fileId, url, type) {
  currentAnalysisFileId = fileId;
  const section = document.getElementById('analysisSection');
  const preview = document.getElementById('analysisPreview');
  const result = document.getElementById('analysisResult');
  const error = document.getElementById('analysisError');

  section.hidden = false;
  result.hidden = true;
  error.hidden = true;

  if (type === 'video') {
    preview.innerHTML = `<video src="${url}" controls muted style="max-width:100%;max-height:300px"></video>`;
  } else {
    preview.innerHTML = `<img src="${url}" alt="preview" style="max-width:100%;max-height:300px" />`;
  }

  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function runAnalysis() {
  if (!currentAnalysisFileId) return;
  const prompt = document.getElementById('analysisPrompt').value.trim() || '请详细描述这张图片的内容';
  const resultDiv = document.getElementById('analysisResult');
  const errorDiv = document.getElementById('analysisError');
  const contentDiv = document.getElementById('analysisContent');
  const metaDiv = document.getElementById('analysisMeta');
  const btn = document.getElementById('analyzeBtn');

  resultDiv.hidden = true;
  errorDiv.hidden = true;
  btn.disabled = true;
  btn.textContent = '分析中…';
  contentDiv.textContent = '';

  try {
    const resp = await fetch(`/api/analyze/${currentAnalysisFileId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });
    const body = await resp.json();

    if (body.code !== 0) {
      throw new Error(body.message || 'Analysis failed');
    }

    const data = body.data;
    if (data.error) {
      errorDiv.textContent = data.content || '分析失败';
      errorDiv.hidden = false;
      return;
    }

    contentDiv.textContent = data.content || '无分析结果';
    if (data.tokens || data.model) {
      metaDiv.textContent = [
        data.model ? `模型: ${data.model}` : '',
        data.tokens?.input ? `输入: ${data.tokens.input} tokens` : '',
        data.tokens?.output ? `输出: ${data.tokens.output} tokens` : '',
      ].filter(Boolean).join(' | ');
    }
    resultDiv.hidden = false;
  } catch (err) {
    errorDiv.textContent = err.message || '网络错误';
    errorDiv.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = '分析';
  }
}

// --- Reconstruction ---
async function startReconstruction() {
  const dir = document.getElementById('reconImagesDir').value.trim();
  if (!dir) return;

  const statusDiv = document.getElementById('reconStatus');
  const statusText = document.getElementById('reconStatusText');
  const progressText = document.getElementById('reconProgress');
  const errorDiv = document.getElementById('reconError');
  const btn = document.getElementById('startReconBtn');

  statusDiv.hidden = false;
  errorDiv.hidden = true;
  btn.disabled = true;
  btn.textContent = '启动中…';
  statusText.textContent = '请求中';

  try {
    const resp = await fetch('/api/reconstruct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images_dir: dir }),
    });
    const body = await resp.json();
    const data = body.data || {};

    statusText.textContent = data.status || 'unknown';
    progressText.textContent = (data.progress || 0) + '%';

    if (data.status === 'completed') {
      if (data.trajectory_file) {
        document.getElementById('loadTrajectoryBtn').hidden = false;
      }
    }
    if (data.error) {
      errorDiv.textContent = data.error;
      errorDiv.hidden = false;
    }
  } catch (err) {
    errorDiv.textContent = err.message || '请求失败';
    errorDiv.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = '开始重建';
  }
}

async function refreshReconstructions() {
  const container = document.getElementById('reconJobs');
  try {
    const resp = await fetch('/api/reconstruct');
    const body = await resp.json();
    const jobs = body.data || [];

    if (jobs.length === 0) {
      container.innerHTML = '<div class="gallery__empty">暂无重建任务</div>';
      return;
    }

    container.innerHTML = jobs.map(j => `
      <div class="recon-job">
        <div class="recon-job__header">
          <span class="recon-job__id">${j.job_id}</span>
          <span class="recon-job__status ${j.status}">${j.status}</span>
        </div>
        <div>输入: ${j.images_dir || '—'}</div>
        <div>进度: ${j.progress || 0}%</div>
        ${j.error ? `<div style="color:var(--error)">错误: ${j.error}</div>` : ''}
        ${j.trajectory_file ? `<div><a href="/api/reconstruct/${j.job_id}/trajectory" target="_blank">下载轨迹</a></div>` : ''}
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<div class="gallery__empty">加载失败</div>';
  }
}

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  // Register Service Worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/service-worker.js');
  }
  initUpload();
  refreshGallery();

  // Refresh button
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) refreshBtn.addEventListener('click', refreshGallery);

  // Analysis button
  const analyzeBtn = document.getElementById('analyzeBtn');
  if (analyzeBtn) analyzeBtn.addEventListener('click', runAnalysis);

  // Close analysis
  const closeBtn = document.getElementById('closeAnalysis');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      document.getElementById('analysisSection').hidden = true;
      currentAnalysisFileId = null;
    });
  }

  // Keyboard shortcut: Ctrl+Enter to run analysis
  const promptInput = document.getElementById('analysisPrompt');
  if (promptInput) {
    promptInput.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'Enter') runAnalysis();
    });
  }

  // 3D Viewer
  const loadSampleBtn = document.getElementById('loadSampleBtn');
  if (loadSampleBtn) {
    loadSampleBtn.addEventListener('click', () => {
      initViewer3D();
      loadSamplePointCloud();
    });
  }

  // Reconstruction
  const startReconBtn = document.getElementById('startReconBtn');
  if (startReconBtn) startReconBtn.addEventListener('click', startReconstruction);

  const refreshReconBtn = document.getElementById('refreshReconBtn');
  if (refreshReconBtn) refreshReconBtn.addEventListener('click', refreshReconstructions);

  // Init 3D viewer on first interaction
  initViewer3D();
  refreshReconstructions();
});
