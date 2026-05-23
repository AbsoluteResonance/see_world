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

  async function startSlam3rStream() {
    const statusEl = document.getElementById('streamStatus');
    const statsEl = document.getElementById('streamStats');
    const btn = document.getElementById('startStreamBtn');
    const stopBtn = document.getElementById('stopStreamBtn');

    try {
      // Request camera
      mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });

      // Show preview
      const videoEl = document.getElementById('streamPreview');
      if (videoEl) {
        videoEl.srcObject = mediaStream;
        videoEl.hidden = false;
        videoEl.play();
      }

      statusEl.textContent = '连接 WebSocket…';

      // Connect WebSocket
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/slam3r/stream`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        // Start stream session
        ws.send(JSON.stringify({ type: 'start' }));
        statusEl.textContent = '已连接，等待帧…';
      };

      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);

        if (msg.type === 'stream_started') {
          streamId = msg.stream_id;
          statusEl.textContent = '流已建立，开始发送帧';
          btn.hidden = true;
          stopBtn.hidden = false;

          // Start sending frames
          sendFrames();
        }

        if (msg.type === 'cloud_update') {
          const points = msg.points || [];
          const total = msg.total_points || 0;
          const frameCount = msg.frame_count || 0;

          if (statsEl) {
            statsEl.textContent = `帧: ${frameCount} | 点: ${total.toLocaleString()}`;
          }

          // Incremental update to dense viewer
          if (window.denseViewer && points.length > 0) {
            // For now, re-load full cloud periodically
            // TODO: true incremental point addition
          }
        }

        if (msg.type === 'stream_stopped') {
          statusEl.textContent = '流已停止';
          cleanupStream();
        }

        if (msg.type === 'error') {
          statusEl.textContent = `错误: ${msg.message}`;
        }
      };

      ws.onerror = () => {
        statusEl.textContent = 'WebSocket 连接错误';
      };

      ws.onclose = () => {
        if (streamId) {
          statusEl.textContent = '连接已断开';
        }
        cleanupStream();
      };
    } catch (err) {
      statusEl.textContent = `相机错误: ${err.message}`;
    }
  }

  function sendFrames() {
    if (!ws || ws.readyState !== WebSocket.OPEN || !streamId) return;

    const videoEl = document.getElementById('streamPreview');
    if (!videoEl || !videoEl.videoWidth) {
      animationFrameId = requestAnimationFrame(sendFrames);
      return;
    }

    // Capture frame at reduced rate (every 3rd animation frame)
    frameCount++;
    if (frameCount % 3 !== 0) {
      animationFrameId = requestAnimationFrame(sendFrames);
      return;
    }

    // Draw video frame to canvas → JPEG base64
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoEl, 0, 0, 640, 480);

    canvas.toBlob((blob) => {
      const reader = new FileReader();
      reader.onload = () => {
        const base64 = reader.result.split(',')[1];
        const msg = {
          type: 'frame',
          stream_id: streamId,
          timestamp: Date.now() / 1000,
          image: base64,
          resolution: { width: 640, height: 480 },
        };
        ws.send(JSON.stringify(msg));
      };
      reader.readAsDataURL(blob);
    }, 'image/jpeg', 0.7);

    animationFrameId = requestAnimationFrame(sendFrames);
  }

  function stopSlam3rStream() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stop', stream_id: streamId }));
    }
    cleanupStream();
  }

  function cleanupStream() {
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach(t => t.stop());
      mediaStream = null;
    }
    const btn = document.getElementById('startStreamBtn');
    const stopBtn = document.getElementById('stopStreamBtn');
    if (btn) btn.hidden = false;
    if (stopBtn) stopBtn.hidden = true;
    streamId = null;
  }

  // ── Init ──

  document.addEventListener('DOMContentLoaded', () => {
    // Offline: SLAM3R button
    const startBtn = document.getElementById('startSlam3rBtn');
    if (startBtn) startBtn.addEventListener('click', startSlam3rReconstruction);

    // Online: stream buttons
    const streamBtn = document.getElementById('startStreamBtn');
    if (streamBtn) streamBtn.addEventListener('click', startSlam3rStream);

    const stopBtn = document.getElementById('stopStreamBtn');
    if (stopBtn) stopBtn.addEventListener('click', stopSlam3rStream);
  });

  // Expose for cross-module access
  window.slam3r = {
    startSlam3rReconstruction,
    startSlam3rStream,
    stopSlam3rStream,
  };
})();
