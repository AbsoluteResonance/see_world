/**
 * Dense Point Cloud 3D Viewer (Three.js)
 * Separate instance for dense reconstruction results.
 */
(function () {
  'use strict';

  let scene, camera, renderer, controls;
  let pointCloudGroup;
  let isInitialized = false;

  const container = document.getElementById('denseViewer3d-container');
  const statusEl = document.getElementById('denseViewer3d-status');

  function init() {
    if (isInitialized) return;

    const rect = container.getBoundingClientRect();
    const w = rect.width || 800;
    const h = rect.height || 500;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);

    camera = new THREE.PerspectiveCamera(60, w / h, 0.01, 1000);
    camera.position.set(0, 1, 3);

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    controls.update();

    // Lights
    const ambient = new THREE.AmbientLight(0x404060);
    scene.add(ambient);
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(1, 2, 1);
    scene.add(dir);
    const dir2 = new THREE.DirectionalLight(0xffffff, 0.4);
    dir2.position.set(-1, -1, -1);
    scene.add(dir2);

    // Grid helper
    const grid = new THREE.GridHelper(10, 20, 0x444466, 0x333355);
    scene.add(grid);

    // Axes helper
    const axes = new THREE.AxesHelper(1);
    scene.add(axes);

    pointCloudGroup = new THREE.Group();
    scene.add(pointCloudGroup);

    // Resize
    window.addEventListener('resize', onResize);

    isInitialized = true;
    animate();
  }

  function animate() {
    if (!isInitialized) return;
    requestAnimationFrame(animate);
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
  }

  /**
   * Parse PLY text and extract colored point cloud.
   */
  function parsePLY(text) {
    const lines = text.split('\n');
    let vertexCount = 0;
    let headerEnd = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith('element vertex')) {
        vertexCount = parseInt(line.split(' ')[2], 10);
      }
      if (line === 'end_header') {
        headerEnd = i + 1;
        break;
      }
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

  /**
   * Load a PLY point cloud from URL.
   */
  function loadPointCloud(url) {
    init();
    setStatus('加载中...');

    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
      })
      .then(text => {
        clear();
        const data = parsePLY(text);
        if (data.count === 0) {
          setStatus('点云数据为空');
          return;
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(data.positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(data.colors, 3));

        const material = new THREE.PointsMaterial({
          size: 0.03,
          vertexColors: true,
          sizeAttenuation: true,
          opacity: 0.9,
          transparent: true,
        });

        const points = new THREE.Points(geometry, material);
        pointCloudGroup.add(points);

        // Auto-fit camera
        geometry.computeBoundingBox();
        const box = geometry.boundingBox;
        if (box) {
          const center = new THREE.Vector3();
          box.getCenter(center);
          const size = new THREE.Vector3();
          box.getSize(size);
          const maxDim = Math.max(size.x, size.y, size.z) || 1;
          controls.target.copy(center);
          camera.position.set(center.x, center.y, center.z + maxDim * 2);
          controls.update();
        }

        setStatus(`稠密点云加载完成 (${data.count} 个点)`);
      })
      .catch(err => {
        setStatus('加载失败: ' + err.message);
        console.error('[dense viewer]', err);
      });
  }

  function resetView() {
    if (!isInitialized) return;
    controls.target.set(0, 0, 0);
    camera.position.set(0, 1, 3);
    controls.update();
  }

  // Public API
  window.denseViewer = { loadPointCloud, resetView, clear };

  // Wire UI
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('resetDenseViewBtn')?.addEventListener('click', resetView);
    document.getElementById('loadDenseBtn')?.addEventListener('click', () => {
      // Triggered from app.js when dense point cloud is available
    });
  });
})();
