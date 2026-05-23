# APP Module — Mobile Client

## Architecture

The See World mobile app follows a three-phase evolution:

```
Phase A: PWA (已完成)
  → Mobile browser access, camera via getUserMedia
  → Upload + Kimi analysis + result display

Phase B: React Native (当前)
  → Full native app with camera, GPS, IMU access
  → Upload + analysis + 3D preview

Phase C: Native AR (未来)
  → ARKit/ARCore integration for real-time 3D overlay
  → On-device SLAM integration
```

## Phase A: PWA

**Location:** `app/pwa/`

The PWA is served from the main web server. It adds:
- `manifest.json` — installable on mobile home screen
- `service-worker.js` — offline caching for faster loads
- Camera access via `navigator.mediaDevices.getUserMedia()`
- GPS access via `navigator.geolocation.watchPosition()`

**Limitations of PWA:**
- Cannot access raw camera frames for real-time SLAM
- Camera access requires HTTPS (use cloudflared tunnel)
- No background processing

## Phase B: React Native (Planned)

**Key libraries:**
- `react-native-vision-camera` — high-fps camera access
- `react-native-sensors` — IMU (accelerometer + gyroscope)
- `@react-native-community/geolocation` — GPS
- `react-native-webview` — embed web gallery/analysis UI
- `react-native-fs` — file upload with progress

**Project structure:**
```
app/
├── pwa/              # PWA files (Phase A)
├── rn-app/           # React Native project (Phase B, TBD)
│   ├── App.tsx
│   ├── screens/
│   │   ├── CameraScreen.tsx
│   │   ├── UploadScreen.tsx
│   │   └── GalleryScreen.tsx
│   ├── services/
│   │   └── api.ts    # Backend API client
│   └── package.json
└── README.md
```

## API Client

All mobile clients communicate with the backend via REST API:

```typescript
// Example: Upload image
const formData = new FormData();
formData.append('file', { uri: photo.uri, type: 'image/jpeg', name: 'photo.jpg' });
const res = await fetch('https://your-server/api/upload/image', {
  method: 'POST',
  body: formData,
});
```

## Setup for Development

### PWA
Just access the web app from a mobile browser → "Add to Home Screen"

### React Native
```bash
cd app/rn-app
npm install
npx react-native run-android  # or run-ios
```
