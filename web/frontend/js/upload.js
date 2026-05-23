/* Upload Module */

function initUpload() {
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const progressBar = document.getElementById('uploadProgress');
  const progressFill = document.getElementById('progressFill');
  const progressText = document.getElementById('progressText');

  if (!dropZone) return;

  // Click to select — but prevent double-firing with label
  dropZone.addEventListener('click', (e) => {
    if (e.target.closest('.drop-zone__btn')) return; // label handles it
    fileInput.value = '';
    fileInput.click();
  });

  // File selected via dialog
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
      uploadFiles(fileInput.files);
      fileInput.value = ''; // allow re-selecting same file
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
    progressFill.style.width = '0%';
    progressText.textContent = '0%';
    const total = files.length;
    let completed = 0;
    let hasError = false;

    function uploadOne(file) {
      const isVideo = file.type.startsWith('video/');
      const endpoint = isVideo ? '/api/upload/video' : '/api/upload/image';

      const form = new FormData();
      form.append('file', file);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', endpoint, true);
      xhr.timeout = 300000; // 5min timeout for large files

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const filePct = Math.round((e.loaded / e.total) * 100);
          const overallPct = Math.round(((completed + e.loaded / e.total) / total) * 100);
          progressFill.style.width = Math.min(overallPct, 100) + '%';
          progressText.textContent = Math.min(overallPct, 100) + '%';
        }
      };

      xhr.onload = () => {
        completed++;
        if (xhr.status >= 400) {
          hasError = true;
          console.error('Upload failed:', file.name, xhr.status, xhr.responseText);
        }
        const overallPct = Math.round((completed / total) * 100);
        progressFill.style.width = overallPct + '%';
        progressText.textContent = overallPct + '%';
        if (completed === total) {
          finishUpload(hasError);
        }
      };

      xhr.onerror = () => {
        completed++;
        hasError = true;
        console.error('Upload network error:', file.name);
        if (completed === total) finishUpload(true);
      };

      xhr.ontimeout = () => {
        completed++;
        hasError = true;
        console.error('Upload timeout:', file.name);
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
