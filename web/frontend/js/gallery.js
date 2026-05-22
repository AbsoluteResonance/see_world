/* Gallery Module */

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
      const isVideo = f.type === 'video';
      return `
        <div class="gallery__item" data-file-id="${f.file_id}" data-url="${f.url}" data-type="${f.type}">
          ${isVideo
            ? `<video src="${f.url}" muted preload="metadata"></video>`
            : `<img src="${f.url}" alt="${f.filename}" loading="lazy" />`
          }
          <span class="gallery__badge">${isVideo ? 'VIDEO' : 'IMG'}</span>
          <span class="gallery__name">${f.filename}</span>
        </div>
      `;
    }).join('');

    // Click handler for gallery items
    document.querySelectorAll('.gallery__item').forEach(el => {
      el.addEventListener('click', () => {
        const fid = el.dataset.fileId;
        const url = el.dataset.url;
        const type = el.dataset.type;
        if (window.openAnalysis) window.openAnalysis(fid, url, type);
      });
    });

  } catch (err) {
    console.error('Failed to load gallery:', err);
    gallery.innerHTML = '<div class="gallery__empty">加载失败，请刷新</div>';
  }
}
