/**
 * Dense Point Cloud 3D Viewer (Three.js)
 * - Binary PLY loading via ArrayBuffer (fast)
 * - Adaptive point size based on scene bounding box
 * - First-person fly mode + direction buttons + fullscreen
 * - Incremental point merging for WebSocket streaming
 */
(function () {
  'use strict';

  let scene, camera, renderer, controls;
  let pointCloudGroup;
  let isInitialized = false;
  let isFullscreen = false;
  let isFlyMode = false;

  // Fly state
  const flyState = { forward: 0, right: 0, up: 0, speed: 0.5, sensitivity: 0.002 };
  let pointerLocked = false;

  const container = document.getElementById('denseViewer3d-container');
  const statusEl = document.getElementById('denseViewer3d-status');
  const section = document.getElementById('denseViewerSection');

  // Accumulated geometry for streaming
  let accumPositions = null;   // Float32Array
  let accumColors = null;      // Float32Array (0-1)
  let accumCount = 0;
  const MAX_ACCUM = 1000000;   // 1M point cap for streaming

  // ── Init ──

  function init() {
    if (isInitialized) return;

    const rect = container.getBoundingClientRect();
    const w = rect.width || 800;
    const h = rect.height || 500;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);

    camera = new THREE.PerspectiveCamera(60, w / h, 0.01, 1000);
    camera.position.set(0, 1, 3);

    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    controls.update();

    // Lights
    scene.add(new THREE.AmbientLight(0x404060));
    const d1 = new THREE.DirectionalLight(0xffffff, 0.8);
    d1.position.set(1, 2, 1);
    scene.add(d1);
    const d2 = new THREE.DirectionalLight(0xffffff, 0.4);
    d2.position.set(-1, -1, -1);
    scene.add(d2);

    scene.add(new THREE.GridHelper(10, 20, 0x444466, 0x333355));
    scene.add(new THREE.AxesHelper(1));

    pointCloudGroup = new THREE.Group();
    scene.add(pointCloudGroup);

    window.addEventListener('resize', onResize);
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('keyup', onKeyUp);
    document.addEventListener('pointerlockchange', onPointerLockChange);
    renderer.domElement.addEventListener('mousemove', onMouseMove);
    renderer.domElement.addEventListener('click', onViewerClick);

    isInitialized = true;
    animate();
  }

  function animate() {
    if (!isInitialized) return;
    requestAnimationFrame(animate);

    // Fly movement — touch devices don't need pointer lock
    const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    if (isFlyMode && (pointerLocked || isTouch) && (flyState.forward || flyState.right || flyState.up)) {
      const dir = new THREE.Vector3();
      camera.getWorldDirection(dir);
      dir.y = 0;
      dir.normalize();
      const right = new THREE.Vector3();
      right.crossVectors(camera.up, dir).normalize();
      const spd = flyState.speed;

      if (flyState.forward) camera.position.addScaledVector(dir, flyState.forward * spd);
      if (flyState.right) camera.position.addScaledVector(right, flyState.right * spd);
      if (flyState.up) camera.position.y += flyState.up * spd;
    }

    controls.update();
    renderer.render(scene, camera);
  }

  function onResize() {
    if (!isInitialized) return;
    const rect = container.getBoundingClientRect();
    const w = rect.width || 800;
    const h = rect.height || 500;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }

  // ── Fly mode input ──

  function onKeyDown(e) {
    if (!isFlyMode) return;
    switch (e.key.toLowerCase()) {
      case 'w': flyState.forward = 1; break;
      case 's': flyState.forward = -1; break;
      case 'a': flyState.right = -1; break;
      case 'd': flyState.right = 1; break;
      case 'q': flyState.up = 1; break;
      case 'e': flyState.up = -1; break;
      case 'escape': exitFlyMode(); break;
    }
  }

  function onKeyUp(e) {
    if (!isFlyMode) return;
    switch (e.key.toLowerCase()) {
      case 'w': case 's': flyState.forward = 0; break;
      case 'a': case 'd': flyState.right = 0; break;
      case 'q': case 'e': flyState.up = 0; break;
    }
  }

  function onMouseMove(e) {
    if (!isFlyMode || !pointerLocked) return;
    const mx = e.movementX * flyState.sensitivity;
    const my = e.movementY * flyState.sensitivity;
    // Yaw
    camera.rotateY(-mx);
    // Pitch
    camera.rotateX(-my);
    // Clamp pitch
    const euler = new THREE.Euler().setFromQuaternion(camera.quaternion, 'YXZ');
    euler.x = Math.max(-Math.PI / 2.1, Math.min(Math.PI / 2.1, euler.x));
    camera.quaternion.setFromEuler(euler);
    controls.target.copy(camera.position).add(new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion));
  }

  function onViewerClick() {
    if (isFlyMode && !pointerLocked) {
      renderer.domElement.requestPointerLock();
    }
  }

  function onPointerLockChange() {
    pointerLocked = document.pointerLockElement === renderer.domElement;
  }

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg;
  }

  function clear() {
    if (!pointCloudGroup) return;
    while (pointCloudGroup.children.length) {
      const child = pointCloudGroup.children[0];
      if (child.geometry) child.geometry.dispose();
      if (child.material) child.material.dispose();
      pointCloudGroup.remove(child);
    }
    accumPositions = null;
    accumColors = null;
    accumCount = 0;
  }

  // ── Binary PLY parser ──

  function parsePLYBinary(arrayBuffer) {
    const bytes = new Uint8Array(arrayBuffer);
    // Find header end
    const endMarker = new TextEncoder().encode('end_header\n');
    let headerEnd = -1;
    for (let i = 0; i <= bytes.length - endMarker.length; i++) {
      let match = true;
      for (let j = 0; j < endMarker.length; j++) {
        if (bytes[i + j] !== endMarker[j]) { match = false; break; }
      }
      if (match) { headerEnd = i + endMarker.length; break; }
    }
    if (headerEnd < 0) throw new Error('Invalid PLY: no end_header');

    const headerText = new TextDecoder().decode(bytes.slice(0, headerEnd));
    let vertexCount = 0;
    for (const line of headerText.split('\n')) {
      if (line.startsWith('element vertex')) {
        vertexCount = parseInt(line.split(' ')[2], 10);
      }
    }
    if (!vertexCount) throw new Error('PLY has no vertices');

    // Body: 16 bytes per point: f4(x,y,z) + u1(r,g,b) + u1(pad)
    const body = arrayBuffer.slice(headerEnd);
    const stride = 16;
    const n = Math.min(vertexCount, Math.floor(body.byteLength / stride));

    const positions = new Float32Array(n * 3);
    const colors = new Float32Array(n * 3);
    const dv = new DataView(body);

    for (let i = 0; i < n; i++) {
      const off = i * stride;
      positions[i * 3] = dv.getFloat32(off, true);
      positions[i * 3 + 1] = dv.getFloat32(off + 4, true);
      positions[i * 3 + 2] = dv.getFloat32(off + 8, true);
      colors[i * 3] = dv.getUint8(off + 12) / 255;
      colors[i * 3 + 1] = dv.getUint8(off + 13) / 255;
      colors[i * 3 + 2] = dv.getUint8(off + 14) / 255;
    }

    return { positions, colors, count: n };
  }

  // ── Fallback ASCII parser (for backward compat) ──

  function parsePLYASCII(text) {
    const lines = text.split('\n');
    let vertexCount = 0, headerEnd = 0;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith('element vertex')) vertexCount = parseInt(line.split(' ')[2], 10);
      if (line === 'end_header') { headerEnd = i + 1; break; }
    }
    const positions = new Float32Array(vertexCount * 3);
    const colors = new Float32Array(vertexCount * 3);
    let idx = 0;
    for (let i = headerEnd; i < lines.length && idx < vertexCount; i++) {
      const parts = lines[i].trim().split(/\s+/);
      if (parts.length < 6) continue;
      positions[idx * 3] = parseFloat(parts[0]);
      positions[idx * 3 + 1] = parseFloat(parts[1]);
      positions[idx * 3 + 2] = parseFloat(parts[2]);
      colors[idx * 3] = parseInt(parts[3], 10) / 255;
      colors[idx * 3 + 1] = parseInt(parts[4], 10) / 255;
      colors[idx * 3 + 2] = parseInt(parts[5], 10) / 255;
      idx++;
    }
    return { positions, colors, count: idx };
  }

  // ── Shared: set up a point cloud geometry / material ──

  function createPointCloud(data) {
    if (data.count === 0) return null;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(data.positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(data.colors, 3));

    // Adaptive point size from bounding box
    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    if (!box) return null;

    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const adaptiveSize = maxDim * 0.006;  // 0.6% of scene size

    const material = new THREE.PointsMaterial({
      size: adaptiveSize,
      vertexColors: true,
      sizeAttenuation: true,
    });

    const points = new THREE.Points(geometry, material);

    // Auto-fit camera
    const center = new THREE.Vector3();
    box.getCenter(center);
    controls.target.copy(center);
    camera.position.set(center.x, center.y, center.z + maxDim * 2);
    controls.update();

    return { points, center, size: new THREE.Vector3(size.x, size.y, size.z) };
  }

  // ── Public: load from URL ──

  function loadPointCloud(url) {
    init();
    setStatus('加载中...');

    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.arrayBuffer();
      })
      .then(buffer => {
        clear();

        // Detect binary vs ASCII
        const headerBytes = new Uint8Array(buffer.slice(0, 4));
        const isBinary = headerBytes[0] === 0x70 && headerBytes[1] === 0x6c && headerBytes[2] === 0x79; // "ply\n"

        if (!isBinary) {
          // ASCII fallback
          const text = new TextDecoder().decode(buffer);
          const data = parsePLYASCII(text);
          const result = createPointCloud(data);
          if (result) {
            pointCloudGroup.add(result.points);
            setStatus(`点云加载完成 (${data.count.toLocaleString()} 个点)`);
          } else {
            setStatus('点云数据为空');
          }
          return;
        }

        const data = parsePLYBinary(buffer);
        const result = createPointCloud(data);
        if (result) {
          pointCloudGroup.add(result.points);
          setStatus(`点云加载完成 (${data.count.toLocaleString()} 个点)`);
        } else {
          setStatus('点云数据为空');
        }
      })
      .catch(err => {
        setStatus('加载失败: ' + err.message);
        console.error('[dense viewer]', err);
      });
  }

  // ── Public: add increment points (WebSocket streaming) ──

  function addPoints(newPoints) {
    init();
    if (!newPoints || newPoints.length === 0) return;

    if (accumCount + newPoints.length > MAX_ACCUM) return; // cap reached

    // Grow accumulated buffers
    const newTotal = accumCount + newPoints.length;
    const newPos = new Float32Array(newTotal * 3);
    const newCol = new Float32Array(newTotal * 3);
    if (accumPositions) {
      newPos.set(accumPositions);
      newCol.set(accumColors);
    }
    for (let i = 0; i < newPoints.length; i++) {
      const p = newPoints[i];
      const off = (accumCount + i) * 3;
      newPos[off] = p[0];
      newPos[off + 1] = p[1];
      newPos[off + 2] = p[2];
      newCol[off] = p[3] / 255;
      newCol[off + 1] = p[4] / 255;
      newCol[off + 2] = p[5] / 255;
    }
    accumPositions = newPos;
    accumColors = newCol;
    accumCount = newTotal;

    // Remove old merged geometry, add new one
    let existingMerged = pointCloudGroup.getObjectByName('stream_merged');
    if (existingMerged) {
      existingMerged.geometry.dispose();
      existingMerged.material.dispose();
      pointCloudGroup.remove(existingMerged);
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(accumPositions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(accumColors, 3));

    // Compute bounding box for adaptive sizing
    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    let ptsSize = 0.05; // default
    if (box) {
      const sz = new THREE.Vector3();
      box.getSize(sz);
      ptsSize = Math.max(sz.x, sz.y, sz.z, 1) * 0.008;
    }

    const material = new THREE.PointsMaterial({
      size: ptsSize,
      vertexColors: true,
      sizeAttenuation: true,
    });

    const points = new THREE.Points(geometry, material);
    points.name = 'stream_merged';
    pointCloudGroup.add(points);

    setStatus(`实时点云更新: ${accumCount.toLocaleString()} 个点`);
  }

  // ── Fullscreen ──

  function toggleFullscreen() {
    isFullscreen = !isFullscreen;
    const el = section || container;
    if (isFullscreen) {
      el.classList.add('viewer-fullscreen');
      document.body.style.overflow = 'hidden';
    } else {
      el.classList.remove('viewer-fullscreen');
      document.body.style.overflow = '';
      exitFlyMode();
    }
    // Resize Three.js renderer
    setTimeout(onResize, 100);
  }

  // ── Fly mode ──

  function toggleFlyMode() {
    isFlyMode = !isFlyMode;
    const flyPanel = document.getElementById('flyControls');
    const hint = document.getElementById('flyHint');
    const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

    if (isFlyMode) {
      controls.enabled = false;
      if (flyPanel) flyPanel.style.display = 'flex';
      if (hint) {
        hint.style.display = '';
        hint.querySelector('.viewer-hint').textContent = isTouch
          ? '方向键移动点云 | 单指旋转视角 | 双指缩放 | ESC 退出飞行'
          : '鼠标移动视角 | WASD 移动 | QE 升降 | 滚轮调速度 | ESC 退出飞行';
      }
      renderer.domElement.style.cursor = 'crosshair';
      // Only request pointer lock on non-touch devices
      if (!isTouch) {
        renderer.domElement.requestPointerLock();
      }
    } else {
      exitFlyMode();
    }
  }

  function exitFlyMode() {
    isFlyMode = false;
    controls.enabled = true;
    pointerLocked = false;
    flyState.forward = 0;
    flyState.right = 0;
    flyState.up = 0;
    const flyPanel = document.getElementById('flyControls');
    const hint = document.getElementById('flyHint');
    if (flyPanel) flyPanel.style.display = 'none';
    if (hint) hint.style.display = 'none';
    renderer.domElement.style.cursor = '';
    if (document.pointerLockElement) document.exitPointerLock();
  }

  function resetView() {
    if (!isInitialized) return;
    if (isFlyMode) exitFlyMode();
    controls.target.set(0, 0, 0);
    camera.position.set(0, 1, 3);
    controls.update();
  }

  // ── Speed control ──

  window.setFlySpeed = function (s) {
    flyState.speed = parseFloat(s);
  };

  // ── Public API ──

  window.denseViewer = {
    loadPointCloud,
    addPoints,
    resetView,
    clear,
    toggleFullscreen,
    toggleFlyMode,
    init,
  };

  // ── Wire UI ──

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('resetDenseViewBtn')?.addEventListener('click', resetView);
    document.getElementById('fullscreenDenseBtn')?.addEventListener('click', toggleFullscreen);
    document.getElementById('flyModeBtn')?.addEventListener('click', toggleFlyMode);
    document.getElementById('flySpeedSlider')?.addEventListener('input', function () {
      window.setFlySpeed(this.value);
    });
    // Direction buttons — support both mouse and touch
    const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    ['fw','bk','lt','rt','dn','up'].forEach(dir => {
      const btn = document.getElementById('flyBtn' + dir.charAt(0).toUpperCase() + dir.slice(1));
      if (!btn) return;
      const start = (e) => { e.preventDefault(); setFlyButton(dir, true); };
      const end = (e) => { e.preventDefault(); setFlyButton(dir, false); };
      btn.addEventListener('pointerdown', start);
      btn.addEventListener('pointerup', end);
      btn.addEventListener('pointercancel', end);
      // Only use touch events on touch devices; pointer events handle desktop
      btn.addEventListener('touchstart', start, { passive: false });
      btn.addEventListener('touchend', end);
      btn.addEventListener('touchcancel', end);
    });
  });

  function setFlyButton(dir, pressed) {
    const val = pressed ? 1 : 0;
    switch (dir) {
      case 'fw': flyState.forward = val; break;
      case 'bk': flyState.forward = -val; break;
      case 'rt': flyState.right = val; break;
      case 'lt': flyState.right = -val; break;
      case 'up': flyState.up = val; break;
      case 'dn': flyState.up = -val; break;
    }
  }
})();
