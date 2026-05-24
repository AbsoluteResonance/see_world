/* Reconstruction polling & result UI */
(function () {
  'use strict';

  var currentReconJobId = null;
  var pollIntervalId = null;

  function startReconPolling(jobId) {
    currentReconJobId = jobId;

    var bar = document.getElementById('reconProgressBar');
    var fill = document.getElementById('reconProgressFill');
    var text = document.getElementById('reconProgressText');
    var actions = document.getElementById('reconResultActions');

    if (bar) bar.hidden = false;
    if (fill) fill.style.width = '0%';
    if (text) { text.textContent = '正在离线重建…'; text.style.color = ''; }
    if (actions) actions.hidden = true;

    if (pollIntervalId) clearInterval(pollIntervalId);

    pollIntervalId = setInterval(function () {
      fetch('/api/slam3r/reconstruct/' + jobId)
        .then(function (r) { return r.json(); })
        .then(function (body) {
          var job = body.data || {};
          var fillEl = document.getElementById('reconProgressFill');
          var textEl = document.getElementById('reconProgressText');
          if (fillEl) fillEl.style.width = (job.progress || 0) + '%';
          if (textEl) textEl.textContent = job.progress_message || '正在离线重建…';

          if (job.status === 'completed') {
            clearInterval(pollIntervalId);
            pollIntervalId = null;
            showReconResult(jobId);
          } else if (job.status === 'failed') {
            clearInterval(pollIntervalId);
            pollIntervalId = null;
            if (textEl) {
              textEl.textContent = '重建失败: ' + (job.error || '未知错误');
              textEl.style.color = 'var(--error)';
            }
          }
        })
        .catch(function (e) { console.error('Recon poll error:', e); });
    }, 2000);
  }

  function showReconResult(jobId) {
    var bar = document.getElementById('reconProgressBar');
    if (bar) {
      setTimeout(function () { bar.hidden = true; }, 2500);
    }

    var textEl = document.getElementById('reconProgressText');
    if (textEl) { textEl.textContent = '重建完成 ✓'; textEl.style.color = 'var(--success)'; }

    var actions = document.getElementById('reconResultActions');
    if (actions) actions.hidden = false;

    // Wire buttons — remove old listeners by cloning
    var downloadPlyBtn = document.getElementById('downloadPlyBtn');
    var downloadScreenshotsBtn = document.getElementById('downloadScreenshotsBtn');
    var viewPlyBtn = document.getElementById('viewPointCloudBtn');

    if (downloadPlyBtn) {
      downloadPlyBtn.onclick = function () {
        window.open('/api/slam3r/reconstruct/' + jobId + '/pointcloud', '_blank');
      };
    }
    if (downloadScreenshotsBtn) {
      downloadScreenshotsBtn.onclick = function () {
        window.open('/api/slam3r/reconstruct/' + jobId + '/screenshots', '_blank');
      };
    }
    if (viewPlyBtn) {
      viewPlyBtn.onclick = function () {
        if (window.denseViewer && window.denseViewer.loadPointCloud) {
          window.denseViewer.loadPointCloud('/api/slam3r/reconstruct/' + jobId + '/pointcloud');
          var section = document.getElementById('denseViewerSection');
          if (section) section.scrollIntoView({ behavior: 'smooth' });
        }
      };
    }
  }

  function triggerReconstruction(fileId) {
    fetch('/api/slam3r/reconstruct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: fileId }),
    })
      .then(function (r) { return r.json(); })
      .then(function (body) {
        if (body.code === 0 && body.data) {
          startReconPolling(body.data.job_id);
        } else {
          alert('启动重建失败: ' + (body.message || ''));
        }
      })
      .catch(function (err) { alert('启动重建失败: ' + err.message); });
  }

  window.startReconPolling = startReconPolling;
  window.triggerReconstruction = triggerReconstruction;
})();
