/**
 * MASt3R-SLAM — Frontend for real-time dense 3D reconstruction.
 */
(function () {
  'use strict';

  // ── Online Streaming ──

  let mediaStream = null;
  let animationFrameId = null;
  let httpLoopActive = false;
  var mast3rIntervalId = null;
  var mast3rPollId = null;
  var firstFrame = true;
  var mast3rMaxPoints = 500;

  async function startMast3rStream() {
    const statusEl = document.getElementById('streamStatus');
    const btn = document.getElementById('startStreamBtnMast3r');
    const stopBtn = document.getElementById('stopStreamBtn');

    if (btn) btn.hidden = true;
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

      statusEl.textContent = 'MASt3R-SLAM — 启动中…';
      if (window.denseViewer && window.denseViewer.init) {
        try { window.denseViewer.init(); } catch (e) { console.error('init err:', e); }
      }
      firstFrame = true;
      httpLoopActive = true;
      startMast3rLoop();
    } catch (err) {
      statusEl.textContent = '相机错误: ' + (err.message || '');
      if (btn) btn.hidden = false;
      if (stopBtn) stopBtn.hidden = true;
    }
  }

  function startMast3rLoop() {
    var st = document.getElementById('streamStatus');

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
      var saveFlag = document.getElementById('saveFramesCheck')?.checked || false;
      fetch('/api/slam3r/mast3r/frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: b64, timestamp: performance.now() / 1000, save: saveFlag, max_points: mast3rMaxPoints }),
      }).catch(function () {});
    }, 1500);

    // Loop 2: Poll points every 3 seconds
    mast3rPollId = setInterval(function () {
      if (!httpLoopActive) { clearInterval(mast3rPollId); return; }
      var st3 = document.getElementById('streamStatus');
      fetch('/api/slam3r/mast3r/points').then(function (r) { return r.json(); }).then(function (body) {
        var data = body.data || {};
        var pts = data.points || [];
        if (st3) st3.textContent = 'MASt3R-SLAM | ' + (data.frames_processed || 0) + ' 帧 | ' + (data.total_points || 0).toLocaleString() + ' 点';
        if (window.denseViewer && pts.length > 0) {
          try { window.denseViewer.addPoints(pts); } catch (e) { console.error('addPoints:', e); }
          if (firstFrame) { firstFrame = false; st3.textContent += ' ✓ 首次加载'; }
        }
      }).catch(function () {});
    }, 3000);
  }

  function stopMast3rStream() {
    if (mast3rIntervalId) { clearInterval(mast3rIntervalId); mast3rIntervalId = null; }
    if (mast3rPollId) { clearInterval(mast3rPollId); mast3rPollId = null; }
    httpLoopActive = false;
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
    var btn = document.getElementById('startStreamBtnMast3r');
    var stopBtn = document.getElementById('stopStreamBtn');
    var statusEl = document.getElementById('streamStatus');
    if (btn) btn.hidden = false;
    if (stopBtn) stopBtn.hidden = true;
    if (statusEl) statusEl.hidden = true;
  }

  // ── Status check ──

  async function checkStatus() {
    try {
      var resp = await fetch('/api/slam3r/status');
      var body = await resp.json();
      var data = body.data || {};
      var mast3r = data.mast3r_slam || {};
      var badge = document.createElement('span');
      badge.style.cssText = 'font-size:0.6rem;font-weight:normal;margin-left:0.5rem;padding:0.1rem 0.4rem;border-radius:4px;';
      if (mast3r.gpu) {
        badge.style.background = 'rgba(34,197,94,0.2)';
        badge.style.color = 'var(--success)';
        badge.textContent = 'GPU: ' + (mast3r.gpu || '');
      }
      var h2 = document.querySelector('#streamSection .section-header h2');
      if (h2) h2.appendChild(badge);
    } catch (e) {}
  }

  // ── Init ──

  document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('startStreamBtnMast3r')?.addEventListener('click', startMast3rStream);
    document.getElementById('stopStreamBtn')?.addEventListener('click', stopMast3rStream);
    document.getElementById('applyMaxPointsBtn')?.addEventListener('click', function () {
      var v = parseInt(document.getElementById('maxPointsInput')?.value || '500', 10);
      if (v < 50) v = 50;
      if (v > 20000) v = 20000;
      mast3rMaxPoints = v;
      document.getElementById('maxPointsInput').value = v;
      var st = document.getElementById('streamStatus');
      if (st && !st.hidden) st.textContent = 'MASt3R-SLAM | 每帧点 → ' + v;
    });
    checkStatus();
  });

  window.slam3r = {
    startMast3rStream: startMast3rStream,
    stopMast3rStream: stopMast3rStream,
  };
})();
