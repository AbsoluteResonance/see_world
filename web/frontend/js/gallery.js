/* Gallery Module — video only + reconstruction trigger */

let currentFiles = [];

async function refreshGallery() {
  const gallery = document.getElementById('gallery');
  if (!gallery) return;

  try {
    const resp = await fetch('/api/files?page=1&size=50');
    const body = await resp.json();
    currentFiles = body.data?.items || [];

    if (currentFiles.length === 0) {
      gallery.innerHTML = '<div class="gallery__empty">暂无文件，请上传</div>';
      return;
    }

    gallery.innerHTML = currentFiles.map(f => {
      return `
        <div class="gallery__item" data-file-id="${f.file_id}" data-url="${f.url}" data-type="${f.type}">
          <video src="${f.url}" muted preload="metadata" poster="/api/files/${f.file_id}/thumbnail"></video>
          <span class="gallery__badge">VIDEO</span>
          <span class="gallery__name">${f.filename}</span>
          <button class="gallery__recon-btn" data-file-id="${f.file_id}">重建点云</button>
        </div>
      `;
    }).join('');

    // Click handler — open preview
    document.querySelectorAll('.gallery__item').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('.gallery__recon-btn')) return;
        const fid = el.dataset.fileId;
        const url = el.dataset.url;
        const type = el.dataset.type;
        if (window.openAnalysis) window.openAnalysis(fid, url, type);
      });
    });

    // Click handler — trigger reconstruction
    document.querySelectorAll('.gallery__recon-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fid = btn.dataset.fileId;
        if (window.triggerReconstruction) window.triggerReconstruction(fid);
      });
    });

  } catch (err) {
    console.error('Failed to load gallery:', err);
    gallery.innerHTML = '<div class="gallery__empty">加载失败，请刷新</div>';
  }
}
