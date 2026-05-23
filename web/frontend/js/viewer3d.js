/* 3D Viewer Module — Three.js point cloud visualization */

let scene, camera, renderer, pointCloud;
let isInitialized = false;

function initViewer3D(containerId = 'viewer3d-container') {
  const container = document.getElementById(containerId);
  if (!container || isInitialized) return;

  // Scene
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0f172a);

  // Camera
  const rect = container.getBoundingClientRect();
  camera = new THREE.PerspectiveCamera(60, rect.width / rect.height, 0.1, 1000);
  camera.position.set(0, 0, 5);

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(rect.width, rect.height);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  // Lighting
  const ambient = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambient);
  const dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(1, 2, 3);
  scene.add(dir);

  // Grid helper
  const grid = new THREE.GridHelper(10, 20, 0x4f46e5, 0x334155);
  scene.add(grid);

  // Axes helper
  const axes = new THREE.AxesHelper(2);
  scene.add(axes);

  // OrbitControls (loaded from CDN)
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;

  // Resize handler
  window.addEventListener('resize', () => {
    const r = container.getBoundingClientRect();
    camera.aspect = r.width / r.height;
    camera.updateProjectionMatrix();
    renderer.setSize(r.width, r.height);
  });

  isInitialized = true;

  // Render loop
  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();
}

function loadPointCloud(url) {
  if (!isInitialized) return;

  // Remove old point cloud
  if (pointCloud) {
    scene.remove(pointCloud);
    pointCloud.geometry.dispose();
    pointCloud.material.dispose();
  }

  // Fetch and parse PLY
  fetch(url)
    .then(res => res.text())
    .then(text => {
      const lines = text.split('\n');
      let vertexCount = 0;
      let headerEnd = 0;
      let isHeader = true;
      const points = [];

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (isHeader) {
          if (line.startsWith('element vertex')) {
            vertexCount = parseInt(line.split(' ')[2]);
          }
          if (line === 'end_header') {
            headerEnd = i + 1;
            isHeader = false;
          }
        } else {
          if (points.length >= vertexCount) break;
          const parts = line.split(/\s+/);
          if (parts.length >= 3) {
            points.push(
              parseFloat(parts[0]),
              parseFloat(parts[1]),
              parseFloat(parts[2])
            );
          }
        }
      }

      if (points.length === 0) {
        // Try loading as binary PLY or use sample data
        loadSamplePointCloud();
        return;
      }

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));

      const material = new THREE.PointsMaterial({
        color: 0x818cf8,
        size: 0.02,
        sizeAttenuation: true,
      });

      pointCloud = new THREE.Points(geometry, material);
      scene.add(pointCloud);

      // Auto-fit camera
      const box = new THREE.Box3().setFromObject(pointCloud);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      camera.position.set(center.x, center.y, center.z + maxDim * 1.5);
      camera.lookAt(center);
    })
    .catch(() => loadSamplePointCloud());
}

function loadSamplePointCloud() {
  // Generate a sample point cloud (helix shape) for demonstration
  const points = [];
  for (let i = 0; i < 2000; i++) {
    const t = i * 0.05;
    points.push(
      Math.cos(t) * t * 0.1,
      Math.sin(t * 2) * 0.3,
      Math.sin(t) * t * 0.1
    );
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));

  const colors = new Float32Array(points.length);
  for (let i = 0; i < points.length / 3; i++) {
    colors[i * 3] = 0.5 + 0.5 * Math.sin(i * 0.1);
    colors[i * 3 + 1] = 0.3 + 0.3 * Math.cos(i * 0.15);
    colors[i * 3 + 2] = 0.8;
  }
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({
    size: 0.03,
    vertexColors: true,
    sizeAttenuation: true,
  });

  if (pointCloud) scene.remove(pointCloud);
  pointCloud = new THREE.Points(geometry, material);
  scene.add(pointCloud);
  document.getElementById('viewer3d-status').textContent = '示例点云（无实际数据）';
}

// Expose for use from app.js
window.initViewer3D = initViewer3D;
window.loadPointCloud = loadPointCloud;
window.loadSamplePointCloud = loadSamplePointCloud;

/**
 * Load camera trajectory as a line + point cloud in the scene.
 * @param {Float32Array|number[]} points - Flat array of x,y,z positions
 */
function loadTrajectoryPoints(points) {
  if (!isInitialized || !points || points.length < 3) return;

  // Remove old trajectory
  if (window._trajectoryGroup) {
    scene.remove(window._trajectoryGroup);
    window._trajectoryGroup.traverse(child => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) child.material.dispose();
    });
  }

  const group = new THREE.Group();

  // Position buffer
  const positions = new Float32Array(points);

  // Points
  const ptGeom = new THREE.BufferGeometry();
  ptGeom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const ptMat = new THREE.PointsMaterial({
    color: 0x818cf8,
    size: 0.03,
    sizeAttenuation: true,
  });
  const ptCloud = new THREE.Points(ptGeom, ptMat);
  group.add(ptCloud);

  // Connecting line
  const lineGeom = new THREE.BufferGeometry();
  lineGeom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const lineMat = new THREE.LineBasicMaterial({ color: 0x4f46e5, linewidth: 1 });
  const line = new THREE.Line(lineGeom, lineMat);
  group.add(line);

  scene.add(group);
  window._trajectoryGroup = group;

  // Auto-fit camera
  const box = new THREE.Box3().setFromObject(group);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 0.1);
  camera.position.set(center.x, center.y, center.z + maxDim * 1.5);
  camera.lookAt(center);
}
window.loadTrajectoryPoints = loadTrajectoryPoints;
