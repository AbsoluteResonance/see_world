/* App Main — Wire everything together */

let currentAnalysisFileId = null;
let currentAnalysisUrl = null;
let currentAnalysisType = null;
let latestTrajectoryUrl = null;
let latestJobId = null;

function openAnalysis(fileId, url, type) {
  currentAnalysisFileId = fileId;
  currentAnalysisUrl = url;
  currentAnalysisType = type;
  const section = document.getElementById('analysisSection');
  const preview = document.getElementById('analysisPreview');
  const result = document.getElementById('analysisResult');
  const error = document.getElementById('analysisError');
  const reconBtn = document.getElementById('start3dReconBtn');

  section.hidden = false;
  result.hidden = true;
  error.hidden = true;

  if (type === 'video') {
    preview.innerHTML = `<video src="${url}" controls muted style="max-width:100%;max-height:300px"></video>`;
  } else {
    preview.innerHTML = `<img src="${url}" alt="preview" style="max-width:100%;max-height:300px" />`;
  }

  // Show action buttons
  if (reconBtn) reconBtn.hidden = (type !== 'video');
  const renameBtn = document.getElementById('renameFileBtn');
  const deleteBtn = document.getElementById('deleteFileBtn');
  if (renameBtn) renameBtn.style.display = '';
  if (deleteBtn) deleteBtn.style.display = '';

  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function renameCurrentFile() {
  if (!currentAnalysisFileId) return;
  const newName = prompt('输入新文件名（保留扩展名）:');
  if (!newName) return;
  try {
    const resp = await fetch(`/api/files/${currentAnalysisFileId}/rename`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName }),
    });
    const body = await resp.json();
    if (body.code !== 0) throw new Error(body.message);
    if (window.refreshGallery) refreshGallery();
  } catch (err) {
    alert('重命名失败: ' + err.message);
  }
}

async function deleteCurrentFile() {
  if (!currentAnalysisFileId) return;
  if (!confirm('确定要删除这个文件吗？此操作不可撤销。')) return;
  try {
    const resp = await fetch(`/api/files/${currentAnalysisFileId}`, { method: 'DELETE' });
    const body = await resp.json();
    if (body.code !== 0) throw new Error(body.message);
    // Close analysis panel
    document.getElementById('analysisSection').hidden = true;
    currentAnalysisFileId = null;
    if (window.refreshGallery) refreshGallery();
  } catch (err) {
    alert('删除失败: ' + err.message);
  }
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

// --- 3D Reconstruction from uploaded file ---
async function startReconstruction() {
  if (!currentAnalysisFileId || currentAnalysisType !== 'video') return;

  const statusDiv = document.getElementById('reconStatus');
  const statusText = document.getElementById('reconStatusText');
  const progressText = document.getElementById('reconProgress');
  const errorDiv = document.getElementById('reconError');
  const btn = document.getElementById('start3dReconBtn');

  statusDiv.hidden = false;
  errorDiv.hidden = true;
  btn.disabled = true;
  btn.textContent = '重建中…';
  statusText.textContent = '请求中';
  progressText.textContent = '5%';

  try {
    const resp = await fetch(`/api/reconstruct/from-file/${encodeURIComponent(currentAnalysisFileId)}`, {
      method: 'POST',
    });
    const body = await resp.json();
    const job = body.data || {};
    // FastAPI error responses use {detail: {message: ...}} format
    const errDetail = body.detail || {};

    if (!job.job_id) {
      const errMsg = job.error || errDetail.message || body.message || '';
      throw new Error(errMsg.includes('File not found')
        ? '文件不存在，请刷新页面后重试'
        : errMsg || '启动失败（请刷新页面后重试）');
    }

    // Poll for completion
    const jobId = job.job_id;
    latestJobId = jobId;
    let done = false;
    let attempts = 0;
    const maxAttempts = 600; // 10 min at 1s intervals

    while (!done && attempts < maxAttempts) {
      await new Promise(r => setTimeout(r, 1000));
      attempts++;

      const statusResp = await fetch(`/api/reconstruct/${jobId}`);
      const statusBody = await statusResp.json();
      const status = statusBody.data || {};

      statusText.textContent = status.status || 'unknown';
      progressText.textContent = (status.progress || 0) + '%';

      if (status.status === 'completed' || status.status === 'failed') {
        done = true;

        if (status.status === 'completed') {
          statusText.textContent = '完成';
          progressText.textContent = '100%';

          // Store URL for potential later use
          latestTrajectoryUrl = `/api/reconstruct/${jobId}/trajectory`;
          const hasTrajectory = status.trajectory_file && status.trajectory_file.length > 0;

          if (hasTrajectory) {
            loadTrajectoryFromUrl(latestTrajectoryUrl);
            statusText.textContent = '完成 ✓';
            document.getElementById('reconStatusText').textContent = '完成 ✓';

            // Show "加载轨迹" button
            const trajBtn = document.getElementById('loadTrajectoryBtn');
            if (trajBtn) trajBtn.style.display = '';

            // Auto-load colored point cloud if available
            if (status.pointcloud_file) {
              setTimeout(() => {
                if (window.loadPointCloud) {
                  window.loadPointCloud(`/api/reconstruct/${jobId}/pointcloud`);
                }
              }, 200);
            }

            // Show "生成稠密点云" button
            const denseBtn = document.getElementById('denseReconBtn');
            if (denseBtn) {
              denseBtn.style.display = '';
              if (!denseBtn._listenerAttached) {
                denseBtn.addEventListener('click', startDenseReconstruction);
                denseBtn._listenerAttached = true;
              }
            }

            // Switch to trajectory viewer
            document.getElementById('viewerSection').scrollIntoView({ behavior: 'smooth' });
          } else {
            statusText.textContent = '无轨迹';
            progressText.textContent = 'SLAM 未能从该视频中提取出相机轨迹。\n请尝试拍摄运动幅度更大的视频。';
          }
        }

        if (status.error) {
          errorDiv.textContent = status.error;
          errorDiv.hidden = false;
          statusText.textContent = '失败';
        }
      }
    }

    if (!done) {
      errorDiv.textContent = '重建超时';
      errorDiv.hidden = false;
    }
  } catch (err) {
    errorDiv.textContent = err.message || '请求失败';
    errorDiv.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = '3D 重建';
  }
}

async function startDenseReconstruction() {
  const btn = document.getElementById('denseReconBtn');
  if (!btn || !latestJobId) return;

  btn.disabled = true;
  btn.textContent = '生成中…（约 1-3 分钟）';

  try {
    const resp = await fetch(`/api/reconstruct/${latestJobId}/dense`, { method: 'POST' });
    const body = await resp.json();
    if (body.code !== 0) throw new Error(body.detail?.message || body.message || '生成失败');

    btn.textContent = '稠密点云已生成 ✓';

    // Show "加载稠密点云" button
    const loadDenseBtn = document.getElementById('loadDenseBtn');
    if (loadDenseBtn) {
      loadDenseBtn.style.display = '';
      loadDenseBtn.onclick = () => {
        if (window.denseViewer) {
          window.denseViewer.loadPointCloud(`/api/reconstruct/${latestJobId}/dense-pointcloud`);
        }
        document.getElementById('denseViewerSection').scrollIntoView({ behavior: 'smooth' });
      };
    }

    // Auto-load?
    setTimeout(() => {
      if (window.denseViewer) {
        window.denseViewer.loadPointCloud(`/api/reconstruct/${latestJobId}/dense-pointcloud`);
      }
      document.getElementById('denseViewerSection').scrollIntoView({ behavior: 'smooth' });
    }, 500);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = '重试生成稠密点云';
    alert('稠密建图失败: ' + err.message);
  }
}

function loadTrajectoryFromUrl(url) {
  fetch(url)
    .then(res => res.text())
    .then(text => {
      const lines = text.trim().split('\n');
      const points = [];
      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        if (parts.length >= 8) {
          // TUM format: tx ty tz qx qy qz qw
          points.push(parseFloat(parts[1]));  // tx
          points.push(parseFloat(parts[2]));  // ty
          points.push(parseFloat(parts[3]));  // tz
        }
      }

      if (points.length === 0) {
        document.getElementById('viewer3d-status').textContent = '轨迹无数据';
        return;
      }

      // Display as a line + points in 3D viewer
      if (window.loadTrajectoryPoints) {
        window.loadTrajectoryPoints(points);
        document.getElementById('viewer3d-status').textContent = `重建轨迹 (${points.length / 3} 个位姿点)`;
      } else {
        loadSamplePointCloud();
      }
    })
    .catch(() => {
      document.getElementById('viewer3d-status').textContent = '加载轨迹失败';
    });
}

// --- Legacy reconstruction (path-based) ---
async function startReconstructionLegacy() {
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
        ${j.trajectory_file ? `
          <div style="margin-top:4px; display:flex; gap:8px; flex-wrap:wrap;">
            <a href="javascript:void(0)" class="recon-load-traj" data-url="/api/reconstruct/${j.job_id}/trajectory" style="color:var(--primary)">查看轨迹(3D)</a>
            <a href="/api/reconstruct/${j.job_id}/trajectory" target="_blank" style="color:var(--text-muted); font-size:0.8rem">下载轨迹</a>
          </div>` : ''}
      </div>
    `).join('');

    // Click handler for "查看轨迹" links
    container.querySelectorAll('.recon-load-traj').forEach(el => {
      el.addEventListener('click', () => {
        latestTrajectoryUrl = el.dataset.url;
        loadTrajectoryFromUrl(latestTrajectoryUrl);
        document.getElementById('loadTrajectoryBtn').style.display = '';
        document.getElementById('viewerSection').scrollIntoView({ behavior: 'smooth' });
      });
    });
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

  // 3D Reconstruction button
  const reconBtn = document.getElementById('start3dReconBtn');
  if (reconBtn) reconBtn.addEventListener('click', startReconstruction);

  // Rename & Delete buttons
  const renameBtn = document.getElementById('renameFileBtn');
  if (renameBtn) renameBtn.addEventListener('click', renameCurrentFile);

  const deleteBtn = document.getElementById('deleteFileBtn');
  if (deleteBtn) deleteBtn.addEventListener('click', deleteCurrentFile);

  // Close analysis
  const closeBtn = document.getElementById('closeAnalysis');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      document.getElementById('analysisSection').hidden = true;
      currentAnalysisFileId = null;
      const rb = document.getElementById('renameFileBtn');
      const db = document.getElementById('deleteFileBtn');
      if (rb) rb.style.display = 'none';
      if (db) db.style.display = 'none';
    });
  }

  // Keyboard shortcut: Ctrl+Enter to run analysis
  const promptInput = document.getElementById('analysisPrompt');
  if (promptInput) {
    promptInput.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'Enter') runAnalysis();
    });
  }

  // 3D Viewer — Load Sample
  const loadSampleBtn = document.getElementById('loadSampleBtn');
  if (loadSampleBtn) {
    loadSampleBtn.addEventListener('click', () => {
      initViewer3D();
      loadSamplePointCloud();
    });
  }

  // 3D Viewer — Load Latest Trajectory
  const loadTrajBtn = document.getElementById('loadTrajectoryBtn');
  if (loadTrajBtn) {
    loadTrajBtn.addEventListener('click', () => {
      if (latestTrajectoryUrl) {
        loadTrajectoryFromUrl(latestTrajectoryUrl);
      }
    });
  }

  // 3D Viewer — Reset View
  const resetViewBtn = document.getElementById('resetViewBtn');
  if (resetViewBtn) {
    resetViewBtn.addEventListener('click', () => {
      if (window.resetCameraView) window.resetCameraView();
    });
  }

  // Legacy reconstruction
  const startReconBtn = document.getElementById('startReconBtn');
  if (startReconBtn) startReconBtn.addEventListener('click', startReconstructionLegacy);

  const refreshReconBtn = document.getElementById('refreshReconBtn');
  if (refreshReconBtn) refreshReconBtn.addEventListener('click', refreshReconstructions);

  // Init 3D viewer on first interaction
  initViewer3D();
  refreshReconstructions();
});
