/* Upload Module */

function initUpload() {
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const progressBar = document.getElementById('uploadProgress');
  const progressFill = document.getElementById('progressFill');
  const progressText = document.getElementById('progressText');

  if (!dropZone) return;

  // Click to select
  dropZone.addEventListener('click', () => fileInput.click());

  // File selected via dialog
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
      uploadFiles(fileInput.files);
    }
  });

  // Drag & drop
  ['dragenter', 'dragover'].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });
  });
  ['dragleave', 'drop'].forEach(evt => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
    });
  });
  dropZone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length) {
      uploadFiles(e.dataTransfer.files);
    }
  });

  function uploadFiles(files) {
    progressBar.hidden = false;
    const total = files.length;
    let completed = 0;

    function uploadOne(file) {
      const isVideo = file.type.startsWith('video/');
      const endpoint = isVideo ? '/api/upload/video' : '/api/upload/image';

      const form = new FormData();
      form.append('file', file);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', endpoint, true);

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const filePct = Math.round((e.loaded / e.total) * 100);
          const overallPct = Math.round(((completed + e.loaded / e.total) / total) * 100);
          progressFill.style.width = Math.min(overallPct, 100) + '%';
          progressText.textContent = overallPct + '%';
        }
      };

      xhr.onload = () => {
        completed++;
        const overallPct = Math.round((completed / total) * 100);
        progressFill.style.width = overallPct + '%';
        progressText.textContent = overallPct + '%';
        if (completed === total) {
          setTimeout(() => {
            progressBar.hidden = true;
            progressFill.style.width = '0%';
            if (window.refreshGallery) window.refreshGallery();
          }, 500);
        }
      };

      xhr.onerror = () => {
        completed++;
        console.error('Upload failed:', file.name);
        if (completed === total) {
          progressBar.hidden = true;
          progressFill.style.width = '0%';
        }
      };

      xhr.send(form);
    }

    for (const file of files) {
      uploadOne(file);
    }
  }
}
