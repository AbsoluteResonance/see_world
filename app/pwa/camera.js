/* See World PWA — Camera + GPS entry */
let mediaStream = null;
let gpsWatchId = null;

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

// Cleanup
function stopCamera() {
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
    mediaStream = null;
  }
}
