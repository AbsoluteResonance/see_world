/* See World PWA — Camera + GPS + WebSocket frame streaming */
let mediaStream = null;
let gpsWatchId = null;
let streamWs = null;
let streamId = null;
let streamActive = false;
let frameCount = 0;
let animFrameId = null;

// Open camera
async function startCamera() {
  const video = document.getElementById('cameraPreview');
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    video.srcObject = mediaStream;
    document.getElementById('cameraStatus').textContent = '相机已开启';
  } catch (err) {
    document.getElementById('cameraStatus').textContent = `相机错误: ${err.message}`;
  }
}

// Capture photo
function capturePhoto() {
  const video = document.getElementById('cameraPreview');
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  canvas.toBlob(blob => {
    uploadPhoto(blob);
  }, 'image/jpeg', 0.9);
}

// Upload captured photo
async function uploadPhoto(blob) {
  const form = new FormData();
  form.append('file', blob, `capture_${Date.now()}.jpg`);
  try {
    const resp = await fetch('/api/upload/image', { method: 'POST', body: form });
    const data = await resp.json();
    document.getElementById('uploadStatus').textContent =
      `上传成功: ${data.data?.file_id || 'OK'}`;
    window.location.href = '/'; // Go to gallery
  } catch (err) {
    document.getElementById('uploadStatus').textContent = `上传失败: ${err.message}`;
  }
}

// Start GPS tracking
function startGPS() {
  if (!navigator.geolocation) {
    document.getElementById('gpsStatus').textContent = 'GPS not available';
    return;
  }
  gpsWatchId = navigator.geolocation.watchPosition(
    pos => {
      document.getElementById('gpsStatus').textContent =
        `纬度: ${pos.coords.latitude.toFixed(6)}, 经度: ${pos.coords.longitude.toFixed(6)}`;
    },
    err => {
      document.getElementById('gpsStatus').textContent = `GPS error: ${err.message}`;
    },
    { enableHighAccuracy: true, timeout: 10000 }
  );
}

// ── WebSocket Real-time Frame Streaming (for SLAM3R) ──

async function startFrameStream() {
  const statusEl = document.getElementById('streamStatusPwa');
  if (!statusEl) return;

  try {
    // Ensure camera is running
    if (!mediaStream) {
      await startCamera();
    }
    if (!mediaStream) {
      statusEl.textContent = '相机不可用';
      return;
    }

    statusEl.textContent = '连接 WebSocket…';

    // Connect to SLAM3R streaming endpoint
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/slam3r/stream`;
    streamWs = new WebSocket(wsUrl);

    streamWs.onopen = () => {
      streamWs.send(JSON.stringify({ type: 'start' }));
      statusEl.textContent = '等待流会话…';
    };

    streamWs.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'stream_started') {
        streamId = msg.stream_id;
        streamActive = true;
        statusEl.textContent = '流已建立，发送帧中…';
        scheduleFrame(); // Start sending frames
      }
      if (msg.type === 'cloud_update') {
        const totalPoints = msg.total_points || 0;
        const frameCountMsg = msg.frame_count || 0;
        statusEl.textContent = `已发送 ${frameCountMsg} 帧, 点云 ${totalPoints.toLocaleString()} 点`;
      }
      if (msg.type === 'error') {
        statusEl.textContent = `错误: ${msg.message}`;
        stopFrameStream();
      }
    };

    streamWs.onerror = () => { statusEl.textContent = 'WebSocket 错误'; };
    streamWs.onclose = () => {
      if (streamActive) {
        statusEl.textContent = '连接断开';
        streamActive = false;
      }
    };
  } catch (err) {
    if (statusEl) statusEl.textContent = `启动失败: ${err.message}`;
  }
}

function scheduleFrame() {
  if (!streamActive || !streamWs || streamWs.readyState !== WebSocket.OPEN) return;

  const video = document.getElementById('cameraPreview');
  if (!video || !video.videoWidth) {
    animFrameId = requestAnimationFrame(scheduleFrame);
    return;
  }

  // Frame rate control: skip 2 out of 3 frames
  frameCount++;
  if (frameCount % 3 !== 0) {
    animFrameId = requestAnimationFrame(scheduleFrame);
    return;
  }

  // Capture frame at reduced resolution (640x480) as JPEG
  const canvas = document.createElement('canvas');
  canvas.width = 640;
  canvas.height = 480;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, 640, 480);

  canvas.toBlob((blob) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (!streamActive || !streamWs || streamWs.readyState !== WebSocket.OPEN) return;
      const base64 = reader.result.split(',')[1];
      streamWs.send(JSON.stringify({
        type: 'frame',
        stream_id: streamId,
        timestamp: Date.now() / 1000,
        image: base64,
        resolution: { width: 640, height: 480 },
      }));
    };
    reader.readAsDataURL(blob);
  }, 'image/jpeg', 0.7);

  animFrameId = requestAnimationFrame(scheduleFrame);
}

function stopFrameStream() {
  streamActive = false;
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  if (streamWs && streamWs.readyState === WebSocket.OPEN) {
    streamWs.send(JSON.stringify({ type: 'stop', stream_id: streamId }));
    streamWs.close();
  }
  streamWs = null;
  streamId = null;
  frameCount = 0;
  const el = document.getElementById('streamStatusPwa');
  if (el) el.textContent = '流已停止';
}

// Cleanup
function stopCamera() {
  stopFrameStream();
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
    mediaStream = null;
  }
}
