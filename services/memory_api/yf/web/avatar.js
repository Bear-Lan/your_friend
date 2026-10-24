import * as THREE from "./vendor/three.module.js";

const host = document.getElementById("avatar-scene");
const pauseButton = document.getElementById("motion-toggle");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let paused = reducedMotion.matches;
let renderer;

function fallback() {
  document.getElementById("avatar-fallback").hidden = false;
  host.querySelector("canvas")?.remove();
  host.setAttribute("aria-label", "yf 陪伴形象；当前设备暂不能显示立体形象");
  pauseButton.hidden = true;
}

try {
  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.35;
  host.append(renderer.domElement);
  renderer.domElement.setAttribute("aria-hidden", "true");
  renderer.domElement.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    renderer.setAnimationLoop(null);
    fallback();
  });

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 40);
  camera.position.set(0.1, 2.35, 7.5);
  camera.lookAt(0, 1.48, 0);
  scene.add(new THREE.HemisphereLight(0xfff7ff, 0xc5b9d9, 3));
  const light = new THREE.DirectionalLight(0xfff4e8, 4.2);
  light.position.set(-3, 6, 5);
  light.castShadow = true;
  light.shadow.mapSize.set(1024, 1024);
  light.shadow.camera.left = -3;
  light.shadow.camera.right = 3;
  light.shadow.camera.top = 4;
  light.shadow.camera.bottom = -2;
  light.shadow.normalBias = 0.035;
  light.shadow.radius = 5;
  scene.add(light);
  const rim = new THREE.DirectionalLight(0xe0d5ff, 3);
  rim.position.set(3, 3, -2);
  scene.add(rim);

  const material = (color, roughness = 0.7) =>
    new THREE.MeshStandardMaterial({ color, roughness });
  const skin = material("#f3d7c2");
  const hair = material("#9d85b9");
  const sweater = material("#b4a2d3");
  const cuff = material("#c9bae1");
  const pants = material("#eee9e1");
  const shoes = material("#fcfaf6");
  const sole = material("#d5cbde");
  const dark = material("#3e354a", 0.22);
  const white = material("#ffffff", 0.3);
  const blush = material("#eebfb9");

  const figure = new THREE.Group();
  figure.rotation.y = -0.14;
  scene.add(figure);
  function mesh(geometry, mat, parent, x, y, z, sx = 1, sy = 1, sz = 1) {
    const object = new THREE.Mesh(geometry, mat);
    object.position.set(x, y, z);
    object.scale.set(sx, sy, sz);
    object.castShadow = true;
    object.receiveShadow = true;
    parent.add(object);
    return object;
  }
  const ball = new THREE.SphereGeometry(1, 40, 28);
  const sphere = (mat, parent, x, y, z, sx, sy, sz) =>
    mesh(ball, mat, parent, x, y, z, sx, sy, sz);
  const capsule = (radius, length, mat, parent, x, y, z) =>
    mesh(
      new THREE.CapsuleGeometry(radius, length, 8, 24),
      mat,
      parent,
      x,
      y,
      z,
    );

  // Rounded, fully modelled humanoid with a soft knitted silhouette.
  const body = new THREE.Group();
  figure.add(body);
  sphere(sweater, body, 0, 1.36, 0, 0.43, 0.5, 0.3);
  mesh(
    new THREE.CylinderGeometry(0.37, 0.39, 0.12, 48),
    cuff,
    body,
    0,
    0.98,
    0,
    1,
    1,
    0.74,
  );
  sphere(cuff, body, 0, 1.77, -0.035, 0.245, 0.13, 0.21);
  capsule(0.105, 0.15, skin, body, 0, 1.86, 0);

  for (const side of [-1, 1]) {
    capsule(0.155, 0.4, pants, figure, side * 0.19, 0.63, -0.005);
    mesh(
      new THREE.CylinderGeometry(0.155, 0.155, 0.1, 32),
      pants,
      figure,
      side * 0.19,
      0.29,
      0,
    );
    sphere(sole, figure, side * 0.19, 0.105, 0.12, 0.19, 0.085, 0.31);
    sphere(shoes, figure, side * 0.19, 0.165, 0.12, 0.18, 0.115, 0.3);
    for (let row = 0; row < 3; row++) {
      const lace = capsule(
        0.012,
        0.12,
        white,
        figure,
        side * 0.19,
        0.245 - row * 0.017,
        0.15 + row * 0.05,
      );
      lace.rotation.z = Math.PI / 2;
    }
  }
  const arms = [];
  for (const side of [-1, 1]) {
    const arm = new THREE.Group();
    arm.position.set(side * 0.38, 1.62, 0);
    arm.rotation.z = side * 0.13;
    body.add(arm);
    capsule(0.17, 0.42, sweater, arm, side * 0.035, -0.235, 0);
    mesh(
      new THREE.CylinderGeometry(0.145, 0.14, 0.12, 32),
      cuff,
      arm,
      side * 0.035,
      -0.55,
      0,
    );
    sphere(skin, arm, side * 0.035, -0.665, 0.015, 0.115, 0.145, 0.105);
    sphere(skin, arm, -side * 0.047, -0.635, 0.08, 0.06, 0.085, 0.06);
    arms.push(arm);
  }

  // A small stitched star, shared with the identity of the interface.
  const star = new THREE.Shape();
  for (let i = 0; i < 8; i++) {
    const angle = Math.PI / 2 + (i * Math.PI) / 4;
    const radius = i % 2 ? 0.036 : 0.09;
    const x = Math.cos(angle) * radius,
      y = Math.sin(angle) * radius;
    if (i === 0) star.moveTo(x, y);
    else star.lineTo(x, y);
  }
  star.closePath();
  mesh(
    new THREE.ExtrudeGeometry(star, {
      depth: 0.012,
      bevelEnabled: true,
      bevelSize: 0.006,
      bevelThickness: 0.004,
      bevelSegments: 2,
      steps: 1,
    }),
    material("#f5e8bf"),
    body,
    0.15,
    1.43,
    0.282,
  );

  const head = new THREE.Group();
  head.position.set(0, 2.3, 0);
  body.add(head);
  sphere(hair, head, 0, 0.055, -0.13, 0.525, 0.57, 0.44);
  sphere(skin, head, 0, -0.015, 0.065, 0.475, 0.51, 0.43);
  sphere(skin, head, -0.47, -0.055, 0.025, 0.09, 0.12, 0.085);
  sphere(skin, head, 0.47, -0.055, 0.025, 0.09, 0.12, 0.085);
  mesh(
    new THREE.SphereGeometry(1, 48, 24, 0, Math.PI * 2, 0, 1.37),
    hair,
    head,
    0,
    0.04,
    0.02,
    0.516,
    0.535,
    0.47,
  );
  for (const [x, y, z, rx] of [
    [-0.32, 0.29, 0.3, -0.4],
    [-0.13, 0.34, 0.41, -0.3],
    [0.08, 0.34, 0.42, -0.4],
    [0.28, 0.32, 0.33, -0.5],
  ]) {
    const bang = sphere(hair, head, x, y, z, 0.18, 0.23, 0.12);
    bang.rotation.z = rx;
  }
  sphere(hair, head, -0.445, 0.035, 0.16, 0.105, 0.285, 0.14);
  sphere(hair, head, 0.445, 0.055, 0.16, 0.105, 0.26, 0.14);
  const eyes = [];
  for (const side of [-1, 1]) {
    const eye = new THREE.Group();
    eye.position.set(side * 0.177, -0.015, 0.46);
    head.add(eye);
    sphere(dark, eye, 0, 0, 0, 0.038, 0.059, 0.025);
    sphere(white, eye, -0.009, 0.02, 0.023, 0.011, 0.014, 0.006);
    eyes.push(eye);
    sphere(blush, head, side * 0.29, -0.14, 0.389, 0.075, 0.032, 0.019);
    const brow = capsule(0.009, 0.067, hair, head, side * 0.18, 0.102, 0.446);
    brow.rotation.z = Math.PI / 2 - side * 0.12;
  }
  sphere(skin, head, 0, -0.106, 0.498, 0.035, 0.032, 0.027);
  const smile = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(-0.075, -0.19, 0.462),
    new THREE.Vector3(0, -0.237, 0.49),
    new THREE.Vector3(0.075, -0.19, 0.462),
  );
  mesh(
    new THREE.TubeGeometry(smile, 20, 0.009, 8, false),
    material("#a47276"),
    head,
    0,
    0,
    0,
  );
  // A soft hairpin is part of the mesh, rather than a screen-space sticker.
  const pin = capsule(
    0.016,
    0.1,
    material("#ead7b2"),
    head,
    -0.386,
    0.225,
    0.381,
  );
  pin.rotation.z = -0.48;

  const plinth = mesh(
    new THREE.CylinderGeometry(1.23, 1.26, 0.11, 96),
    material("#e6dff0"),
    scene,
    0,
    -0.045,
    0,
  );
  plinth.receiveShadow = true;
  const floor = mesh(
    new THREE.PlaneGeometry(12, 12),
    new THREE.ShadowMaterial({ color: "#86729e", opacity: 0.12 }),
    scene,
    0,
    -0.105,
    0,
  );
  floor.rotation.x = -Math.PI / 2;
  floor.castShadow = false;

  const pointer = { x: 0, y: 0 };
  host.addEventListener("pointermove", (event) => {
    const bounds = host.getBoundingClientRect();
    pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    pointer.y = ((event.clientY - bounds.top) / bounds.height) * 2 - 1;
  });
  host.addEventListener("pointerleave", () => {
    pointer.x = 0;
    pointer.y = 0;
  });
  let waveUntil = 0;
  let elapsed = 0;
  let previous = performance.now();
  let lastFrame = 0;
  let drawnPaused = false;
  function wave() {
    if (!paused) waveUntil = elapsed + 2.5;
  }
  host.addEventListener("click", wave);
  document.getElementById("greet-avatar").addEventListener("click", wave);

  function syncPause() {
    pauseButton.textContent = paused ? "播放动作" : "暂停动作";
    pauseButton.setAttribute("aria-pressed", String(paused));
    host.setAttribute(
      "aria-label",
      paused
        ? "yf 立体虚拟伙伴，动作已暂停"
        : "yf 立体虚拟伙伴，穿着淡紫色毛衣，正在轻轻呼吸",
    );
  }
  pauseButton.addEventListener("click", () => {
    paused = !paused;
    syncPause();
  });
  reducedMotion.addEventListener("change", (event) => {
    paused = event.matches;
    syncPause();
  });
  syncPause();
  const observer = new ResizeObserver(() => {
    const width = host.clientWidth,
      height = host.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height);
    camera.aspect = width / height;
    // Maintain the same full-body framing on both a narrow phone and a wide desktop.
    camera.position.z = camera.aspect < 0.66 ? 8.6 : 7.5;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
  });
  observer.observe(host);
  document.addEventListener("visibilitychange", () => {
    previous = performance.now();
  });
  renderer.setAnimationLoop((now) => {
    if (document.hidden || document.getElementById("side-panel").open) {
      previous = now;
      return;
    }
    if (paused && drawnPaused) {
      previous = now;
      return;
    }
    if (now - lastFrame < 33) return;
    const delta = Math.min((now - previous) / 1000, 0.1);
    previous = now;
    lastFrame = now;
    if (!paused) {
      elapsed += delta;
      const state = document.body.dataset.companionState || "idle";
      body.position.y = Math.sin(elapsed * 1.9) * 0.012;
      body.rotation.z = Math.sin(elapsed * 0.7) * 0.018;
      head.rotation.y = THREE.MathUtils.lerp(
        head.rotation.y,
        pointer.x * 0.16,
        0.08,
      );
      head.rotation.x = THREE.MathUtils.lerp(
        head.rotation.x,
        pointer.y * 0.07 + (state === "thinking" ? -0.09 : 0),
        0.08,
      );
      head.rotation.z = THREE.MathUtils.lerp(
        head.rotation.z,
        state === "thinking" ? -0.09 : Math.sin(elapsed * 0.9) * 0.025,
        0.06,
      );
      const blinkPhase = elapsed % 4.7;
      const blink =
        blinkPhase > 4.52
          ? Math.max(0.08, Math.abs(blinkPhase - 4.61) / 0.09)
          : 1;
      eyes.forEach((eye) => {
        eye.scale.y = blink;
      });
      arms[0].rotation.z = -0.13 + Math.sin(elapsed * 1.2) * 0.035;
      const waving = elapsed < waveUntil;
      const target = waving
        ? 2.35 + Math.sin(elapsed * 10) * 0.2
        : 0.13 +
          (state === "answering"
            ? Math.sin(elapsed * 3) * 0.13
            : Math.sin(elapsed * 1.2) * 0.035);
      arms[1].rotation.z = THREE.MathUtils.lerp(
        arms[1].rotation.z,
        target,
        0.13,
      );
    }
    renderer.render(scene, camera);
    drawnPaused = paused;
  });
  window.addEventListener("pagehide", () => {
    renderer.setAnimationLoop(null);
    observer.disconnect();
    scene.traverse((object) => {
      object.geometry?.dispose();
      if (object.material) object.material.dispose();
    });
    renderer.dispose();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) location.reload();
  });
} catch {
  renderer?.dispose();
  fallback();
}
