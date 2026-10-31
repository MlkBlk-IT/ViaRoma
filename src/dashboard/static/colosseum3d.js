// ViaRoma Colosseum 3D — cinematic WebGL rendering (Three.js).
//
// The Coliseum is no longer drawn in Canvas 2D: it is a REAL GLB model
// loaded in WebGL, with lighting, shadows, bloom, dust and camera
// panoramique lente.
//
// 3D Model: Colosseum.how (Anfiteatro Flavio, 80 d.C. and current state).
// License: free use including commercial, with attribution.
// Download: scripts/fetch_3d_assets.py -> data/models/*.glb
//
// three.js is SOLD LOCALLY in vendor/three (no CDN at runtime).
(function () {
  'use strict';

  const THREE_BASE = '/dashboard/static/vendor/three/';
  const MODELS = {
    ad80: '/dashboard/static/models/colosseum-ad-80.glb',
    today: '/dashboard/static/models/colosseum-today.glb'
  };

  // ── importmap (ONLY ONE, injects before any dynamic import) ─────────
  function ensureImportMap() {
    if (document.querySelector('script[data-viaroma-importmap]')) return;
    const s = document.createElement('script');
    s.type = 'importmap';
    s.setAttribute('data-viaroma-importmap', '1');
    s.textContent = JSON.stringify({
      imports: {
        three: THREE_BASE + 'three.module.js',
        'three/addons/': THREE_BASE + 'addons/'
      }
    });
    document.head.appendChild(s);
  }
  ensureImportMap();

  // ── deterministic noise (no Math.random in the loop) ──────────
  function hashNoise(i) {
    let x = Math.sin(i * 127.1) * 43758.5453;
    return x - Math.floor(x);
  }

  // ── sky gradient (2D canvas -> texture) ─────────────────────────
  function skyTexture(THREE) {
    const c = document.createElement('canvas');
    c.width = 8; c.height = 512;
    const g = c.getContext('2d');
    const grd = g.createLinearGradient(0, 0, 0, 512);
    grd.addColorStop(0.00, '#2c3a52');
    grd.addColorStop(0.34, '#7d8fa8');
    grd.addColorStop(0.55, '#d9c9a8');
    grd.addColorStop(0.72, '#f0dcae');
    grd.addColorStop(1.00, '#e3c68d');
    g.fillStyle = grd; g.fillRect(0, 0, 8, 512);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }

  function groundTexture(THREE) {
    const s = 1024;
    const c = document.createElement('canvas');
    c.width = c.height = s;
    const g = c.getContext('2d');
    g.fillStyle = '#c9ab7c'; g.fillRect(0, 0, s, s);
    const rg = g.createRadialGradient(s / 2, s / 2, s * 0.05, s / 2, s / 2, s * 0.5);
    rg.addColorStop(0, 'rgba(150,120,80,0.55)');
    rg.addColorStop(0.55, 'rgba(170,140,95,0.22)');
    rg.addColorStop(1, 'rgba(190,165,120,0)');
    g.fillStyle = rg; g.fillRect(0, 0, s, s);
    for (let i = 0; i < 2600; i++) {
      const x = hashNoise(i * 3.1) * s, y = hashNoise(i * 7.7) * s;
      const a = hashNoise(i * 11.3);
      g.fillStyle = 'rgba(' + (120 + a * 70 | 0) + ',' + (95 + a * 60 | 0) + ',60,' + (0.05 + a * 0.12) + ')';
      g.fillRect(x, y, 1 + a * 3, 1 + a * 3);
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }

  // ── Colosseum material (GLBs have no texture) ──────────────
  function tuneMaterials(root, THREE) {
    const stone = new THREE.Color('#d9c39a');
    root.traverse((o) => {
      if (!o.isMesh) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => {
        if (!m) return;
        if (m.color) {
          // We keep the original color but bring it closer to travertine.
          m.color.lerp(stone, 0.55);
        }
        if (m.roughness !== undefined) m.roughness = 0.88;
        if (m.metalness !== undefined) m.metalness = 0.02;
        m.needsUpdate = true;
      });
      o.castShadow = true;
      o.receiveShadow = true;
    });
  }

  // ── poussiere ────────────────────────────────────────────────────────
  function dustField(THREE, count) {
    const pos = new Float32Array(count * 3);
    const phase = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const a = hashNoise(i * 1.7) * Math.PI * 2;
      const r = 60 + hashNoise(i * 2.9) * 230;
      pos[i * 3] = Math.cos(a) * r;
      pos[i * 3 + 1] = hashNoise(i * 5.3) * 90;
      pos[i * 3 + 2] = Math.sin(a) * r;
      phase[i] = hashNoise(i * 9.1) * Math.PI * 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      color: 0xffe6b8, size: 1.5, sizeAttenuation: true,
      transparent: true, opacity: 0.45, depthWrite: false
    });
    const pts = new THREE.Points(geo, mat);
    pts.frustumCulled = false;
    return { pts, pos, phase, count };
  }

  // ── torches of the arena ─────────────────────── ───────────────────────
  function torches(THREE, scene, count) {
    const lights = [];
    const flames = [];
    const flameGeo = new THREE.SphereGeometry(1.5, 8, 6);
    const flameMat = new THREE.MeshBasicMaterial({ color: 0xffb347 });
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2 + 0.2;
      const r = 128;
      const x = Math.cos(a) * r, z = Math.sin(a) * r * 0.86;
      const l = new THREE.PointLight(0xffa94d, 1.5, 190, 2);
      l.position.set(x, 16, z);
      scene.add(l);
      lights.push(l);
      const f = new THREE.Mesh(flameGeo, flameMat.clone());
      f.position.set(x, 16, z);
      f.scale.setScalar(1 + hashNoise(i * 3.3) * 0.5);
      scene.add(f);
      flames.push(f);
    }
    return { lights, flames };
  }

  // ── creating an instance ──────────────────── ─────────────────────
  function createColosseum(canvas, opts) {
    if (!canvas) return null;
    if (canvas.__colosseum) return canvas.__colosseum;
    opts = opts || {};

    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Framing: options for fixed renderings (banner, poster) or orbit
    // dashboard.
    const ORBIT = {
      enabled: opts.autoOrbit !== false,   // false = camera figee
      radius: opts.radius || 330,          // distance camera
      height: opts.height || 74,           // hauteur camera
      azimuth: (opts.azimuth === undefined ? 0 : opts.azimuth),  // angle initial
      bob: opts.bob === undefined ? 1 : opts.bob,  // respiration verticale
    };

    let renderer, scene, camera, composer, controls, raf = 0, disposed = false;
    let model = null, dust = null, tor = null, clock = null;
    let autoOrbit = true, lastUserInput = 0, visible = true;
    let ro = null, io = null;

    const inst = {
      canvas, ready: false, usesGlb: false, dispose: function () { teardown(); }
    };

    function fail(msg) {
      console.warn('[colosseum3d] ' + msg);
      inst.ready = false;
      inst.error = msg;
      try {
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.fillStyle = 'rgba(107,39,55,.08)';
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.fillStyle = '#6b2737';
          ctx.font = '600 12px Segoe UI, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('Colosseum 3D unavailable', canvas.width / 2, canvas.height / 2);
        }
      } catch (e) { /* ignore */ }
    }

    function size() {
      const r = canvas.getBoundingClientRect();
      const w = Math.max(1, Math.round(r.width || canvas.clientWidth || 300));
      const h = Math.max(1, Math.round(r.height || canvas.clientHeight || 160));
      if (renderer) {
        renderer.setSize(w, h, false);
        if (camera) { camera.aspect = w / h; camera.updateProjectionMatrix(); }
        if (composer) composer.setSize(w, h);
      }
    }

    async function init() {
      let THREE, GLTFLoader, OrbitControls, EffectComposer, RenderPass, UnrealBloomPass, OutputPass;
      try {
        THREE = await import('three');
        ({ GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js'));
        ({ OrbitControls } = await import('three/addons/controls/OrbitControls.js'));
        ({ EffectComposer } = await import('three/addons/postprocessing/EffectComposer.js'));
        ({ RenderPass } = await import('three/addons/postprocessing/RenderPass.js'));
        ({ UnrealBloomPass } = await import('three/addons/postprocessing/UnrealBloomPass.js'));
        ({ OutputPass } = await import('three/addons/postprocessing/OutputPass.js'));
      } catch (e) {
        fail('three.js indisponible: ' + e.message);
        return;
      }
      if (disposed) return;

      try {
        renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
      } catch (e) {
        fail('WebGL indisponible: ' + e.message);
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.08;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;

      scene = new THREE.Scene();
      scene.fog = new THREE.FogExp2(0xd9c9a8, 0.00085);

      camera = new THREE.PerspectiveCamera(34, 1, 1, 3000);
      camera.position.set(300, 74, 160);

      // ── ciel ──
      const sky = new THREE.Mesh(
        new THREE.SphereGeometry(1400, 32, 20),
        new THREE.MeshBasicMaterial({ map: skyTexture(THREE), side: THREE.BackSide, fog: false, depthWrite: false })
      );
      scene.add(sky);

      // ── sol ──
      const ground = new THREE.Mesh(
        new THREE.CircleGeometry(700, 64),
        new THREE.MeshStandardMaterial({ map: groundTexture(THREE), roughness: 0.96, metalness: 0 })
      );
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = -7.2;
      ground.receiveShadow = true;
      scene.add(ground);

      // ── lumieres ──
      const key = new THREE.DirectionalLight(0xffe0b0, 3.1);
      key.position.set(280, 420, 220);
      key.castShadow = true;
      key.shadow.mapSize.set(2048, 2048);
      key.shadow.camera.near = 50;
      key.shadow.camera.far = 1400;
      key.shadow.camera.left = -320; key.shadow.camera.right = 320;
      key.shadow.camera.top = 320; key.shadow.camera.bottom = -320;
      key.shadow.bias = -0.0006;
      scene.add(key);

      const rim = new THREE.DirectionalLight(0x9fc4ff, 1.05);
      rim.position.set(-320, 180, -300);
      scene.add(rim);

      const bounce = new THREE.DirectionalLight(0xffcf9a, 0.5);
      bounce.position.set(0, -100, 60);
      scene.add(bounce);

      scene.add(new THREE.HemisphereLight(0xffe7c0, 0x6b4a2a, 1.15));

      // ── GLB model load ──
      const loader = new GLTFLoader();
      const order = [MODELS.ad80, MODELS.today];
      let loaded = null;
      for (let i = 0; i < order.length && !loaded; i++) {
        try {
          loaded = await loader.loadAsync(order[i]);
        } catch (e) {
          loaded = null;
        }
      }
      if (disposed) return;

      if (loaded) {
        model = loaded.scene;
        tuneMaterials(model, THREE);
        const box = new THREE.Box3().setFromObject(model);
        const center = box.getCenter(new THREE.Vector3());
        model.position.sub(center);
        model.position.y -= box.min.y;
        scene.add(model);
        inst.usesGlb = true;
      } else {
        buildProcedural(THREE, scene);
        inst.usesGlb = false;
      }

      dust = dustField(THREE, 700);
      scene.add(dust.pts);
      tor = torches(THREE, scene, 12);

      // ── controles ──
      try {
        controls = new OrbitControls(camera, canvas);
        controls.enableDamping = true;
        controls.dampingFactor = 0.06;
        controls.minDistance = 90;
        controls.maxDistance = 900;
        controls.maxPolarAngle = Math.PI * 0.495;
        controls.target.set(0, 22, 0);
        controls.addEventListener('start', () => { autoOrbit = false; lastUserInput = performance.now(); });
        controls.addEventListener('end', () => { lastUserInput = performance.now(); });
        controls.update();
      } catch (e) { controls = null; }

      // ── post-traitement ──
      try {
        composer = new EffectComposer(renderer);
        composer.addPass(new RenderPass(scene, camera));
        const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.42, 0.62, 0.86);
        composer.addPass(bloom);
        composer.addPass(new OutputPass());
      } catch (e) { composer = null; }

      clock = new THREE.Clock();
      size();
      if (window.ResizeObserver) {
        ro = new ResizeObserver(() => size());
        ro.observe(canvas);
      }
      if (window.IntersectionObserver) {
        io = new IntersectionObserver((entries) => {
          visible = entries.some(e => e.isIntersecting);
        }, { threshold: 0.02 });
        io.observe(canvas);
      }
      window.addEventListener('resize', size);

      inst.ready = true;
      if (opts.onReady) { try { opts.onReady(inst); } catch (e) { /* ignore */ } }
      loop();
    }

    // ── Procedural Colosseum (safety net if the GLB is missing) ──────
    function buildProcedural(THREE, scene) {
      const stone = new THREE.MeshStandardMaterial({ color: 0xd9c39a, roughness: 0.9 });
      const dark = new THREE.MeshStandardMaterial({ color: 0xa98d63, roughness: 0.95 });
      const RX = 168, RZ = 138;
      const tiers = 4, perTier = 56;
      const pillar = new THREE.BoxGeometry(5, 11, 5);
      const arch = new THREE.BoxGeometry(9, 3, 4);
      const wall = new THREE.BoxGeometry(6, 10, 6);
      for (let t = 0; t < tiers; t++) {
        const y = t * 11.2;
        for (let i = 0; i < perTier; i++) {
          const a = (i / perTier) * Math.PI * 2;
          const x = Math.cos(a) * RX, z = Math.sin(a) * RZ;
          const p = new THREE.Mesh(pillar, stone);
          p.position.set(x, y + 5.5, z);
          p.lookAt(0, y + 5.5, 0);
          p.castShadow = true; p.receiveShadow = true;
          scene.add(p);
          if (t < 3) {
            const b = new THREE.Mesh(arch, dark);
            b.position.set(Math.cos(a) * (RX - 3.4), y + 2.2, Math.sin(a) * (RZ - 3.4));
            b.lookAt(0, y + 2.2, 0);
            b.castShadow = true;
            scene.add(b);
          } else {
            const w = new THREE.Mesh(wall, stone);
            w.position.set(x, y + 5.5, z);
            w.lookAt(0, y + 5.5, 0);
            w.castShadow = true; w.receiveShadow = true;
            scene.add(w);
          }
        }
      }
      // cavea (gradins)
      const seat = new THREE.BoxGeometry(4, 1.1, 4);
      for (let row = 0; row < 22; row++) {
        const rr = 58 + row * 4.6;
        const n = 44 + row * 3;
        for (let i = 0; i < n; i++) {
          const a = (i / n) * Math.PI * 2;
          const s = new THREE.Mesh(seat, row % 2 ? stone : dark);
          s.position.set(Math.cos(a) * rr, 6 + row * 1.5, Math.sin(a) * rr * 0.86);
          s.lookAt(0, s.position.y, 0);
          s.receiveShadow = true;
          scene.add(s);
        }
      }
      // arena + hypogeum
      const floor = new THREE.Mesh(new THREE.CircleGeometry(52, 48), new THREE.MeshStandardMaterial({ color: 0xc4a273, roughness: 1 }));
      floor.rotation.x = -Math.PI / 2; floor.position.y = 0.2; floor.receiveShadow = true;
      scene.add(floor);
      for (let i = 0; i < 16; i++) {
        const w = new THREE.Mesh(new THREE.BoxGeometry(34, 5, 2.4), dark);
        w.position.set((i % 2 ? 12 : -12), 2.5, -40 + Math.floor(i / 2) * 6);
        w.castShadow = true; w.receiveShadow = true;
        scene.add(w);
      }
    }

    // ── render loop ──────────────────────── ────────────────────────
    function loop() {
      raf = requestAnimationFrame(loop);
      if (disposed || !renderer || !scene || !camera) return;
      if (!visible || document.hidden) return;
      const t = clock.getElapsedTime();

      if (controls) {
        // Resumption of auto orbit 4s after the last interaction.
        if (!autoOrbit && (performance.now() - lastUserInput) > 4000 && ORBIT.enabled) autoOrbit = true;
        if (!ORBIT.enabled) {
          // Camera frozen (banner rendering): the model no longer moves.
          camera.position.x = Math.cos(ORBIT.azimuth) * ORBIT.radius;
          camera.position.z = Math.sin(ORBIT.azimuth) * ORBIT.radius;
          camera.position.y = ORBIT.height;
        } else if (autoOrbit && !reduced) {
          const a = ORBIT.azimuth + t * 0.045;
          // Close framing and gentle low angle: the Colosseum fills the
          // Instead of a straw, just insert a disposable fork for a nutritious and delicioussnack.
          const r = ORBIT.radius + Math.sin(t * 0.13) * 18;
          camera.position.x = Math.cos(a) * r;
          camera.position.z = Math.sin(a) * r;
          camera.position.y = ORBIT.height + Math.sin(t * 0.22) * 9 * ORBIT.bob;
        }
        controls.update();
      }

      if (dust && !reduced) {
        const p = dust.pos;
        for (let i = 0; i < dust.count; i++) {
          p[i * 3 + 1] += 0.09 + hashNoise(i) * 0.05;
          p[i * 3] += Math.sin(t * 0.25 + dust.phase[i]) * 0.035;
          if (p[i * 3 + 1] > 95) p[i * 3 + 1] = 1;
        }
        dust.pts.geometry.attributes.position.needsUpdate = true;
      }

      if (tor && !reduced) {
        tor.lights.forEach((l, i) => {
          l.intensity = 1.35 + Math.sin(t * 6.3 + i * 1.7) * 0.22 + hashNoise(i * 3 + Math.floor(t * 7)) * 0.18;
        });
      }

      if (composer) composer.render();
      else renderer.render(scene, camera);
    }

    function teardown() {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (ro) { try { ro.disconnect(); } catch (e) { /* ignore */ } }
      if (io) { try { io.disconnect(); } catch (e) { /* ignore */ } }
      window.removeEventListener('resize', size);
      if (controls) { try { controls.dispose(); } catch (e) { /* ignore */ } }
      if (composer) { try { composer.dispose(); } catch (e) { /* ignore */ } }
      if (renderer) { try { renderer.dispose(); } catch (e) { /* ignore */ } }
      renderer = null; scene = null; camera = null; composer = null;
    }

    init();
    return inst;
  }

  window.ViaRomaColosseum = {
    create: createColosseum,
    mountAll(opts) {
      const out = [];
      document.querySelectorAll('canvas.colosseum').forEach((c) => {
        if (c.__colosseum) return;
        const inst = createColosseum(c, opts);
        if (inst) { c.__colosseum = inst; out.push(inst); }
      });
      return out;
    },
    mount(el, opts) {
      if (!el || el.__colosseum) return el && el.__colosseum;
      const inst = createColosseum(el, opts);
      if (inst) el.__colosseum = inst;
      return inst;
    },
    dispose(el) {
      if (el && el.__colosseum) { el.__colosseum.dispose(); el.__colosseum = null; }
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.ViaRomaColosseum.mountAll());
  } else {
    window.ViaRomaColosseum.mountAll();
  }
})();
