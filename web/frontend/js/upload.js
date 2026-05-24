/* Upload Module — video only + auto offline reconstruction */

function initUpload() {
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const progressBar = document.getElementById('uploadProgress');
  const progressFill = document.getElementById('progressFill');
  const progressText = document.getElementById('progressText');

  if (!dropZone) return;

  dropZone.addEventListener('click', (e) => {
    if (e.target.closest('.drop-zone__btn')) return;
    fileInput.value = '';
    fileInput.click();
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
      uploadFiles(fileInput.files);
      fileInput.value = '';
    }
  });

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
    progressFill.style.width = '0%';
    progressText.textContent = '0%';
    const total = files.length;
    let completed = 0;
    let hasError = false;

    function uploadOne(file) {
      // Only accept videos
      if (!file.type.startsWith('video/')) {
        completed++;
        console.warn('Skipped non-video file:', file.name);
        const pct = Math.round((completed / total) * 100);
        progressFill.style.width = pct + '%';
        progressText.textContent = pct + '%';
        if (completed === total) finishUpload(true);
        return;
      }

      const form = new FormData();
      form.append('file', file);
      const autoRecon = document.getElementById('autoReconstructCheck');
      form.append('auto_reconstruct', autoRecon && autoRecon.checked ? 'true' : 'false');

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload/video', true);
      xhr.timeout = 300000;

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const overallPct = Math.round(((completed + e.loaded / e.total) / total) * 100);
          progressFill.style.width = Math.min(overallPct, 100) + '%';
          progressText.textContent = Math.min(overallPct, 100) + '%';
        }
      };

      xhr.onload = () => {
        completed++;
        if (xhr.status >= 400) {
          hasError = true;
          console.error('Upload failed:', file.name, xhr.status);
        } else {
          // Check for auto reconstruction
          try {
            const resp = JSON.parse(xhr.responseText);
            const jobId = resp.data?.reconstruction_job_id;
            if (jobId && window.startReconPolling) {
              window.startReconPolling(jobId);
            }
          } catch(e) { /* ignore parse errors */ }
        }
        const pct = Math.round((completed / total) * 100);
        progressFill.style.width = pct + '%';
        progressText.textContent = pct + '%';
        if (completed === total) finishUpload(hasError);
      };

      xhr.onerror = () => {
        completed++; hasError = true;
        if (completed === total) finishUpload(true);
      };
      xhr.ontimeout = () => {
        completed++; hasError = true;
        if (completed === total) finishUpload(true);
      };

      xhr.send(form);
    }

    function finishUpload(hadError) {
      setTimeout(() => {
        progressBar.hidden = true;
        progressFill.style.width = '0%';
        progressText.textContent = '0%';
        if (hadError) {
          progressText.textContent = '上传失败，请重试';
          progressText.style.color = 'var(--error)';
          setTimeout(() => { progressText.style.color = ''; }, 3000);
        }
        if (window.refreshGallery) window.refreshGallery();
      }, 500);
    }

    for (const file of files) {
      uploadOne(file);
    }
  }
}
