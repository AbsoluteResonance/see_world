/* App Main — Wire everything together */

let currentAnalysisFileId = null;
let currentAnalysisUrl = null;
let currentAnalysisType = null;

function openAnalysis(fileId, url, type) {
  currentAnalysisFileId = fileId;
  window._currentAnalysisFileId = fileId;  // expose for slam3r.js
  currentAnalysisUrl = url;
  currentAnalysisType = type;
  const section = document.getElementById('analysisSection');
  const preview = document.getElementById('analysisPreview');

  section.hidden = false;

  if (type === 'video') {
    preview.innerHTML = `<video src="${url}" controls muted style="max-width:100%;max-height:300px"></video>`;
  } else {
    preview.innerHTML = `<img src="${url}" alt="preview" style="max-width:100%;max-height:300px" />`;
  }

  // SLAM3R button — only for videos
  const slam3rBtn = document.getElementById('startSlam3rBtn');
  if (slam3rBtn) {
    slam3rBtn.style.display = (type === 'video') ? '' : 'none';
  }
  // Hide previous SLAM3R result when switching files
  const slam3rResult = document.getElementById('slam3rResult');
  if (slam3rResult) slam3rResult.hidden = true;

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
    document.getElementById('analysisSection').hidden = true;
    currentAnalysisFileId = null;
    if (window.refreshGallery) refreshGallery();
  } catch (err) {
    alert('删除失败: ' + err.message);
  }
}

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/service-worker.js');
  }
  initUpload();
  refreshGallery();

  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) refreshBtn.addEventListener('click', refreshGallery);

  const renameBtn = document.getElementById('renameFileBtn');
  if (renameBtn) renameBtn.addEventListener('click', renameCurrentFile);

  const deleteBtn = document.getElementById('deleteFileBtn');
  if (deleteBtn) deleteBtn.addEventListener('click', deleteCurrentFile);

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
});
