/**
 * SLAM3R — Frontend logic for dense 3D reconstruction.
 *
 * Modes:
 *   Offline: Upload video → SLAM3R rebuild → show dense point cloud
 *   Online:  Camera stream → WebSocket → real-time incremental point cloud
 */
(function () {
  'use strict';

  // ── Offline Reconstruction ──

  let currentSlam3rJobId = null;

  async function startSlam3rReconstruction() {
    const fileId = window._currentAnalysisFileId;
    if (!fileId) return;

    const statusEl = document.getElementById('slam3rStatus');
    const progressEl = document.getElementById('slam3rProgress');
    const errorEl = document.getElementById('slam3rError');
    const btn = document.getElementById('startSlam3rBtn');
    const resultPanel = document.getElementById('slam3rResult');

    statusEl.hidden = false;
    errorEl.hidden = true;
    resultPanel.hidden = true;
    btn.disabled = true;
    btn.textContent = '重建中…';
    statusEl.textContent = '请求中…';

    try {
      const resp = await fetch(`/api/slam3r/reconstruct/from-file/${encodeURIComponent(fileId)}`, {
        method: 'POST',
      });
      const body = await resp.json();
      const job = body.data || {};
      const errDetail = body.detail || {};

      if (!job.job_id) {
        const errMsg = job.error || errDetail.message || body.message || '';
        throw new Error(errMsg || '启动 SLAM3R 重建失败');
      }

      currentSlam3rJobId = job.job_id;
      // Poll for completion
      let done = false;
      let attempts = 0;
      const maxAttempts = 600;

      while (!done && attempts < maxAttempts) {
        await new Promise(r => setTimeout(r, 2000));
        attempts++;

        const statusResp = await fetch(`/api/slam3r/reconstruct/${currentSlam3rJobId}`);
        const statusBody = await statusResp.json();
        const status = statusBody.data || {};

        statusEl.textContent = `状态: ${status.status || 'unknown'}`;
        if (progressEl) progressEl.textContent = `进度: ${status.progress || 0}%`;

        if (status.status === 'completed' || status.status === 'failed') {
          done = true;

          if (status.status === 'completed') {
            statusEl.textContent = '✓ 稠密重建完成';
            resultPanel.hidden = false;

            // Enable "查看点云" button
            const viewBtn = document.getElementById('viewSlam3rCloudBtn');
            if (viewBtn) {
              viewBtn.style.display = '';
              viewBtn.onclick = () => {
                if (window.denseViewer) {
                  window.denseViewer.loadPointCloud(`/api/slam3r/reconstruct/${currentSlam3rJobId}/pointcloud`);
                }
                document.getElementById('denseViewerSection').scrollIntoView({ behavior: 'smooth' });
              };
            }

            // Auto-load into dense viewer
            setTimeout(() => {
              if (window.denseViewer) {
                window.denseViewer.loadPointCloud(`/api/slam3r/reconstruct/${currentSlam3rJobId}/pointcloud`);
              }
              document.getElementById('denseViewerSection').scrollIntoView({ behavior: 'smooth' });
            }, 500);
          }

          if (status.error) {
            errorEl.textContent = status.error;
            errorEl.hidden = false;
            statusEl.textContent = '重建失败';
          }
        }
      }

      if (!done) {
        errorEl.textContent = '重建超时（10分钟）';
        errorEl.hidden = false;
      }
    } catch (err) {
      errorEl.textContent = err.message || '请求失败';
      errorEl.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = 'SLAM3R 稠密重建';
    }
  }

  // ── Online Streaming ──

  let ws = null;
  let streamId = null;
  let mediaStream = null;
  let animationFrameId = null;
  let frameCount = 0;
  let reconnectAttempts = 0;
  let streamMode = null;
  let httpLoopActive = false;
  let httpSessionId = null;
  const MAX_RECONNECT = 3;

  async function startSlam3rStream(mode) {
    streamMode = mode || 'slam3r';
    const statusEl = document.getElementById('streamStatus');
    const btnVins = document.getElementById('startStreamBtnVins');
    const btnMast3r = document.getElementById('startStreamBtnMast3r');
    const btnSlam = document.getElementById('startStreamBtnSlam');
    const stopBtn = document.getElementById('stopStreamBtn');

    if (btnVins) btnVins.hidden = true;
    if (btnMast3r) btnMast3r.hidden = true;
    if (btnSlam) btnSlam.hidden = true;
    stopBtn.hidden = false;
    statusEl.hidden = false;
    statusEl.textContent = '请求相机…';

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });

      const videoEl = document.getElementById('streamPreview');
      if (videoEl) {
        videoEl.srcObject = mediaStream;
        videoEl.hidden = false;
        try { await videoEl.play(); } catch (e) { console.error('play err:', e); }
      }

      if (mode === 'mast3r-slam') {
        var vw = videoEl ? videoEl.videoWidth : 0;
        statusEl.textContent = 'MASt3R-SLAM — 启动中… (vw=' + vw + ')';
        if (window.denseViewer && window.denseViewer.init) {
          try { window.denseViewer.init(); } catch (e) { console.error('init err:', e); }
        }
        httpLoopActive = true;
        startMast3rLoop();
      } else {
        // VINS / SLAM3R use WebSocket
        statusEl.textContent = '连接 WebSocket…';
        connectWs();
      }

      function connectWs() {
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(protocol + '//' + window.location.host + '/ws/slam3r/stream');
        ws.onopen = function () {
          ws.send(JSON.stringify({ type: 'start', mode: streamMode }));
          statusEl.textContent = '已连接，等待服务端确认…';
          reconnectAttempts = 0;
        };
        ws.onmessage = function (e) {
          var msg = JSON.parse(e.data);
          if (msg.type === 'stream_started') {
            streamId = msg.stream_id;
            var m = msg.mode || 'slam3r';
            var labels = { 'vins': 'VINS-Mono', 'slam3r': 'SLAM3R', 'mast3r-slam': 'MASt3R-SLAM' };
            statusEl.textContent = (labels[m] || m) + ' — 正在发送相机帧…';
            frameCount = 0;
            if (m === 'vins' && window.denseViewer) window.denseViewer.clear();
            if ((m === 'slam3r' || m === 'mast3r-slam') && window.denseViewer && window.denseViewer.init) {
              window.denseViewer.init();
            }
            sendFrames();
          }
          if (msg.type === 'cloud_update') {
            var points = msg.points || [];
            var total = msg.total_points || 0;
            var fc = msg.frame_count || 0;
            var ml = streamMode === 'vins' ? 'VINS-Mono' : 'SLAM3R';
            statusEl.textContent = ml + ' | ' + fc + ' 帧 | 点云: ' + total.toLocaleString() + (msg.stub ? ' (演示)' : '');
            if (window.denseViewer && points.length > 0) {
              try { window.denseViewer.addPoints(points); } catch (e) { console.error('addPoints:', e); }
            }
          }
          if (msg.type === 'stream_stopped') { statusEl.textContent = '流已停止'; cleanupStream(); }
          if (msg.type === 'error') { statusEl.textContent = '错误: ' + msg.message; }
        };
        ws.onerror = function () { statusEl.textContent = 'WebSocket 连接失败'; };
        ws.onclose = function () {
          if (!streamId) {
            statusEl.textContent = '无法连接到服务器';
            if (btnVins) btnVins.hidden = false;
            if (btnMast3r) btnMast3r.hidden = false;
            if (btnSlam) btnSlam.hidden = false;
            if (stopBtn) stopBtn.hidden = true;
            return;
          }
          if (reconnectAttempts < MAX_RECONNECT) {
            reconnectAttempts++;
            var delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
            statusEl.textContent = '连接断开，' + (delay / 1000) + 's 后重连';
            setTimeout(connectWs, delay);
          } else {
            statusEl.textContent = '连接已断开';
            cleanupStream();
          }
        };
      }
    } catch (err) {
      statusEl.textContent = '相机错误: ' + (err.message || '');
      if (btnVins) btnVins.hidden = false;
      if (btnMast3r) btnMast3r.hidden = false;
      if (btnSlam) btnSlam.hidden = false;
      if (stopBtn) stopBtn.hidden = true;
    }
  }

  // ── HTTP POST frame loop (same pattern as frame_test.html — proven stable) ──

  var mast3rIntervalId = null;
  var mast3rPollId = null;

  function startMast3rLoop() {
    // Use local reference to avoid closure scope issues
    var st = document.getElementById('streamStatus');
    if (st) st.textContent = 'loop_started';
    // Loop 1: Send frames (fire-and-forget)
    mast3rIntervalId = setInterval(function () {
      if (!httpLoopActive) { clearInterval(mast3rIntervalId); return; }
      var videoEl = document.getElementById('streamPreview');
      if (!videoEl || !videoEl.videoWidth) return;
      var dataUrl;
      try {
        var c = document.createElement('canvas');
        c.width = 640; c.height = 480;
        var ctx = c.getContext('2d');
        ctx.drawImage(videoEl, 0, 0, 640, 480);
        dataUrl = c.toDataURL('image/jpeg', 0.7);
      } catch (e) { return; }
      if (!dataUrl) return;
      var b64 = dataUrl.split(',')[1];
      if (!b64) return;
      var st2 = document.getElementById('streamStatus');
      fetch('/api/slam3r/mast3r/frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: b64, timestamp: performance.now() / 1000 }),
      }).then(function () { if (st2) st2.textContent = '帧已发送'; }).catch(function (e) {
        if (st2) st2.textContent = '帧发送失败: ' + e.message;
      });
    }, 1500);

    // Loop 2: Poll points every 3 seconds
    mast3rPollId = setInterval(function () {
      if (!httpLoopActive) { clearInterval(mast3rPollId); return; }
      var st3 = document.getElementById('streamStatus');
      fetch('/api/slam3r/mast3r/points').then(function (r) {
        if (st3) st3.textContent = 'points_status=' + r.status + ' len=' + (r.headers.get('content-length') || '?');
        return r.json();
      }).then(function (body) {
        var data = body.data || {};
        var pts = data.points || [];
        if (st3) st3.textContent = 'MASt3R-SLAM | ' + (data.frames_processed || 0) + ' 帧 | ' + (data.total_points || 0).toLocaleString() + ' 点 | pts=' + pts.length;
        if (window.denseViewer && pts.length > 0) {
          try { window.denseViewer.addPoints(pts); } catch (e) { console.error('addPoints:', e); }
        }
      }).catch(function (e) {
        if (st3) st3.textContent = 'poll_err: ' + e.message;
      });
    }, 3000);
  }

  function sendFrames() {
    if (!ws || ws.readyState !== WebSocket.OPEN || !streamId) return;
    var videoEl = document.getElementById('streamPreview');
    if (!videoEl || !videoEl.videoWidth) { animationFrameId = requestAnimationFrame(sendFrames); return; }
    frameCount++;
    if (frameCount % 3 !== 0) { animationFrameId = requestAnimationFrame(sendFrames); return; }
    var canvas, ctx;
    try {
      canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
      ctx = canvas.getContext('2d'); ctx.drawImage(videoEl, 0, 0, 640, 480);
    } catch (e) { animationFrameId = requestAnimationFrame(sendFrames); return; }
    var frameTs = performance.now() / 1000;
    var imuSnap = window._lastImuReading;
    canvas.toBlob(function (blob) {
      if (!blob) return;
      var reader = new FileReader();
      reader.onload = function () {
        if (!ws || ws.readyState !== WebSocket.OPEN || !streamId) return;
        var msg = {
          type: 'frame', stream_id: streamId, timestamp: frameTs,
          image: reader.result.split(',')[1], resolution: { width: 640, height: 480 },
        };
        if (imuSnap && imuSnap.acc) { msg.acc = imuSnap.acc; msg.gyr = imuSnap.gyr || [0, 0, 0]; msg.imu_ts = imuSnap.ts; }
        ws.send(JSON.stringify(msg));
      };
      reader.readAsDataURL(blob);
    }, 'image/jpeg', 0.7);
    animationFrameId = requestAnimationFrame(sendFrames);
  }

  function stopSlam3rStream() {
    if (mast3rIntervalId) { clearInterval(mast3rIntervalId); mast3rIntervalId = null; }
    if (mast3rPollId) { clearInterval(mast3rPollId); mast3rPollId = null; }
    httpLoopActive = false;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stop', stream_id: streamId }));
    }
    cleanupStream();
  }

  function cleanupStream() {
    if (mast3rIntervalId) { clearInterval(mast3rIntervalId); mast3rIntervalId = null; }
    if (mast3rPollId) { clearInterval(mast3rPollId); mast3rPollId = null; }
    httpLoopActive = false;
    if (animationFrameId) { cancelAnimationFrame(animationFrameId); animationFrameId = null; }
    if (mediaStream) { mediaStream.getTracks().forEach(function (t) { t.stop(); }); mediaStream = null; }
    var videoEl = document.getElementById('streamPreview');
    if (videoEl) { videoEl.srcObject = null; videoEl.hidden = true; }
    var btnVins = document.getElementById('startStreamBtnVins');
    var btnMast3r = document.getElementById('startStreamBtnMast3r');
    var btnSlam = document.getElementById('startStreamBtnSlam');
    var stopBtn = document.getElementById('stopStreamBtn');
    var statusEl = document.getElementById('streamStatus');
    if (btnVins) btnVins.hidden = false;
    if (btnMast3r) btnMast3r.hidden = false;
    if (btnSlam) btnSlam.hidden = false;
    if (stopBtn) stopBtn.hidden = true;
    if (statusEl) statusEl.hidden = true;
    streamId = null; ws = null;
  }

  // ── Job Listing ──

  async function listJobs() {
    const container = document.getElementById('slam3rJobs');
    if (!container) return;

    try {
      const resp = await fetch('/api/slam3r/reconstruct');
      const body = await resp.json();
      const jobs = body.data || [];

      if (jobs.length === 0) {
        container.innerHTML = '<div class="gallery__empty">暂无 SLAM3R 重建任务</div>';
        return;
      }

      container.innerHTML = jobs.map(j => `
        <div class="recon-job">
          <div class="recon-job__header">
            <span class="recon-job__id">${j.job_id}</span>
            <span class="recon-job__status ${j.status}">${j.status}</span>
          </div>
          <div>进度: ${j.progress || 0}%</div>
          ${j.error ? `<div style="color:var(--error)">${j.error}</div>` : ''}
          ${j.pointcloud_file ? `
            <div style="margin-top:4px; display:flex; gap:8px; flex-wrap:wrap;">
              <a href="javascript:void(0)" class="slam3r-load-cloud" data-url="/api/slam3r/reconstruct/${j.job_id}/pointcloud" style="color:var(--primary)">查看点云</a>
              <a href="/api/slam3r/reconstruct/${j.job_id}/pointcloud" target="_blank" style="color:var(--text-muted); font-size:0.8rem">下载 PLY</a>
            </div>` : ''}
        </div>
      `).join('');

      container.querySelectorAll('.slam3r-load-cloud').forEach(el => {
        el.addEventListener('click', () => {
          if (window.denseViewer) {
            window.denseViewer.loadPointCloud(el.dataset.url);
          }
          document.getElementById('denseViewerSection').scrollIntoView({ behavior: 'smooth' });
        });
      });
    } catch (err) {
      container.innerHTML = '<div class="gallery__empty">加载失败: ' + err.message + '</div>';
    }
  }

  // ── Backend status check ──

  async function checkStatus() {
    const headerEl = document.querySelector('#slam3rSection .section-header h2');
    if (!headerEl) return;

    try {
      const resp = await fetch('/api/slam3r/status');
      const body = await resp.json();
      const data = body.data || {};
      const gpu = data.gpu || {};

      const existingBadge = headerEl.querySelector('.status-badge');
      if (existingBadge) existingBadge.remove();

      const badge = document.createElement('span');
      badge.className = 'status-badge';
      badge.style.cssText = 'font-size:0.6rem;font-weight:normal;margin-left:0.5rem;padding:0.1rem 0.4rem;border-radius:4px;';

      if (gpu.available) {
        badge.style.background = 'rgba(34,197,94,0.2)';
        badge.style.color = 'var(--success)';
        badge.textContent = `GPU: ${gpu.memory_gb || '?'}GB`;
      } else {
        badge.style.background = 'rgba(148,163,184,0.2)';
        badge.style.color = 'var(--text-muted)';
        badge.textContent = 'CPU';
      }
      headerEl.appendChild(badge);
    } catch (err) {
      // silent
    }
  }

  // ── Init ──

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('startSlam3rBtn')?.addEventListener('click', startSlam3rReconstruction);
    document.getElementById('startStreamBtnVins')?.addEventListener('click', function(){startSlam3rStream('vins');});
    document.getElementById('startStreamBtnMast3r')?.addEventListener('click', function(){startSlam3rStream('mast3r-slam');});
    document.getElementById('startStreamBtnSlam')?.addEventListener('click', function(){startSlam3rStream('slam3r');});
    document.getElementById('stopStreamBtn')?.addEventListener('click', stopSlam3rStream);
    document.getElementById('refreshSlam3rBtn')?.addEventListener('click', listJobs);
    document.getElementById('flySpeedSlider')?.addEventListener('input', function () {
      document.getElementById('flySpeedVal').textContent = this.value;
    });

    listJobs();
    checkStatus();
  });

  window.slam3r = {
    startSlam3rReconstruction,
    startSlam3rStream,
    stopSlam3rStream,
    listJobs,
  };
})();
