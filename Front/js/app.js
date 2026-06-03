import * as THREE from "../libs/three.module.js";
import { OrbitControls } from "../libs/OrbitControls.js";

const apiUrl = window.apiUrl || ((path) => path);

const params = {
  enableWind: true,
  showBall: false,
  togglePins: togglePins,
};

const DAMPING = 0.03;
const DRAG = 1 - DAMPING;
const MASS = 0.1;
const restDistance = 25;

const xSegs = 10;
const ySegs = 10;

const clothFunction = plane(restDistance * xSegs, restDistance * ySegs);

const cloth = new Cloth(xSegs, ySegs);

const GRAVITY = 981 * 1.4;
const gravity = new THREE.Vector3(0, -GRAVITY, 0).multiplyScalar(MASS);

const TIMESTEP = 18 / 1000;
const TIMESTEP_SQ = TIMESTEP * TIMESTEP;

let pins = [];

const windForce = new THREE.Vector3(0, 0, 0);

const ballPosition = new THREE.Vector3(0, -45, 0);
const ballSize = 60;

const tmpForce = new THREE.Vector3();

const TESTING = false; // Declared TESTING variable

function plane(width, height) {
  return (u, v, target) => {
    const x = (u - 0.5) * width;
    const y = (v + 0.5) * height;
    const z = 0;

    target.set(x, y, z);
  };
}

function Particle(x, y, z, mass) {
  this.position = new THREE.Vector3();
  this.previous = new THREE.Vector3();
  this.original = new THREE.Vector3();
  this.a = new THREE.Vector3(0, 0, 0);
  this.mass = mass;
  this.invMass = 1 / mass;
  this.tmp = new THREE.Vector3();
  this.tmp2 = new THREE.Vector3();

  clothFunction(x, y, this.position);
  clothFunction(x, y, this.previous);
  clothFunction(x, y, this.original);
}

Particle.prototype.addForce = function (force) {
  this.a.add(this.tmp2.copy(force).multiplyScalar(this.invMass));
};

Particle.prototype.integrate = function (timesq) {
  const newPos = this.tmp.subVectors(this.position, this.previous);
  newPos.multiplyScalar(DRAG).add(this.position);
  newPos.add(this.a.multiplyScalar(timesq));

  this.tmp = this.previous;
  this.previous = this.position;
  this.position = newPos;

  this.a.set(0, 0, 0);
};

const diff = new THREE.Vector3();

function satisfyConstraints(p1, p2, distance) {
  diff.subVectors(p2.position, p1.position);
  const currentDist = diff.length();
  if (currentDist === 0) return;
  const correction = diff.multiplyScalar(1 - distance / currentDist);
  const correctionHalf = correction.multiplyScalar(0.5);
  p1.position.add(correctionHalf);
  p2.position.sub(correctionHalf);
}

function Cloth(w, h) {
  w = w || 10;
  h = h || 10;
  this.w = w;
  this.h = h;

  const particles = [];
  const constraints = [];

  for (let v = 0; v <= h; v++) {
    for (let u = 0; u <= w; u++) {
      particles.push(new Particle(u / w, v / h, 0, MASS));
    }
  }

  for (let v = 0; v < h; v++) {
    for (let u = 0; u < w; u++) {
      constraints.push([
        particles[index(u, v)],
        particles[index(u, v + 1)],
        restDistance,
      ]);

      constraints.push([
        particles[index(u, v)],
        particles[index(u + 1, v)],
        restDistance,
      ]);
    }
  }

  for (let u = w, v = 0; v < h; v++) {
    constraints.push([
      particles[index(u, v)],
      particles[index(u, v + 1)],
      restDistance,
    ]);
  }

  for (let v = h, u = 0; u < w; u++) {
    constraints.push([
      particles[index(u, v)],
      particles[index(u + 1, v)],
      restDistance,
    ]);
  }

  this.particles = particles;
  this.constraints = constraints;

  function index(u, v) {
    return u + v * (w + 1);
  }

  this.index = index;
}

function simulate(now) {
  const windStrength = Math.cos(now / 7000) * 5 + 10;

  windForce.set(
    Math.sin(now / 2000),
    Math.cos(now / 3000),
    Math.sin(now / 1000)
  );
  windForce.normalize();
  windForce.multiplyScalar(windStrength);

  const particles = cloth.particles;

  if (params.enableWind) {
    let indx;
    const normal = new THREE.Vector3();
    const indices = clothGeometry.index;
    const normals = clothGeometry.attributes.normal;

    for (let i = 0, il = indices.count; i < il; i += 3) {
      for (let j = 0; j < 3; j++) {
        indx = indices.getX(i + j);
        normal.fromBufferAttribute(normals, indx);
        tmpForce.copy(normal).normalize().multiplyScalar(normal.dot(windForce));
        particles[indx].addForce(tmpForce);
      }
    }
  }

  for (let i = 0, il = particles.length; i < il; i++) {
    const particle = particles[i];
    particle.addForce(gravity);

    particle.integrate(TIMESTEP_SQ);
  }

  const constraints = cloth.constraints;
  const il = constraints.length;

  for (let i = 0; i < il; i++) {
    const constraint = constraints[i];
    satisfyConstraints(constraint[0], constraint[1], constraint[2]);
  }

  ballPosition.z = -Math.sin(now / 600) * 90;
  ballPosition.x = Math.cos(now / 400) * 70;

  if (params.showBall) {
    sphere.visible = true;

    for (let i = 0, il = particles.length; i < il; i++) {
      const particle = particles[i];
      const pos = particle.position;
      diff.subVectors(pos, ballPosition);
      if (diff.length() < ballSize) {
        diff.normalize().multiplyScalar(ballSize);
        pos.copy(ballPosition).add(diff);
      }
    }
  } else {
    sphere.visible = false;
  }

  for (let i = 0, il = particles.length; i < il; i++) {
    const particle = particles[i];
    const pos = particle.position;
    if (pos.y < -250) {
      pos.y = -250;
    }
  }

  for (let i = 0, il = pins.length; i < il; i++) {
    const xy = pins[i];
    const p = particles[xy];
    p.position.copy(p.original);
    p.previous.copy(p.original);
  }
}

const pinsFormation = [];
pins = [6];

pinsFormation.push(pins);

pins = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
pinsFormation.push(pins);

pins = [0];
pinsFormation.push(pins);

pins = [];
pinsFormation.push(pins);

pins = [0, cloth.w];
pinsFormation.push(pins);

pins = pinsFormation[1];

function togglePins() {
  pins = pinsFormation[~~(Math.random() * pinsFormation.length)];
}

let container, stats;
let camera, scene, renderer;

let clothGeometry;
let sphere;
let object;
let controls;
const loader = new THREE.TextureLoader();

init();
animate(0);

function init() {
  container = document.createElement("div");
  document.body.appendChild(container);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);
  // const bgTexture = loader.load("assets/texture.jpg");
  // scene.background = bgTexture;
  scene.fog = new THREE.Fog(0x000000, 500, 10000);

  camera = new THREE.PerspectiveCamera(
    30,
    window.innerWidth / window.innerHeight,
    1,
    10000
  );
  camera.position.set(1000, 50, 1500);

  scene.add(new THREE.AmbientLight(0x666666));

  const light = new THREE.DirectionalLight(0xdfebff, 1);
  light.position.set(50, 200, 100);
  light.position.multiplyScalar(1.3);

  light.castShadow = true;

  light.shadow.mapSize.width = 1024;
  light.shadow.mapSize.height = 1024;

  const d = 300;

  light.shadow.camera.left = -d;
  light.shadow.camera.right = d;
  light.shadow.camera.top = d;
  light.shadow.camera.bottom = -d;

  light.shadow.camera.far = 1000;

  scene.add(light);

  const clothTexture = loader.load("./image/whits.png");
  clothTexture.anisotropy = 16;

  const clothMaterial = new THREE.MeshLambertMaterial({
    map: clothTexture,
    side: THREE.DoubleSide,
    alphaTest: 0.5,
  });

  clothGeometry = new THREE.ParametricBufferGeometry(
    clothFunction,
    cloth.w,
    cloth.h
  );

  object = new THREE.Mesh(clothGeometry, clothMaterial);
  object.position.set(0, 0, 0);
  object.castShadow = true;
  scene.add(object);

  object.customDepthMaterial = new THREE.MeshDepthMaterial({
    depthPacking: THREE.RGBADepthPacking,
    map: clothTexture,
    alphaTest: 0.5,
  });

  const ballGeo = new THREE.SphereGeometry(ballSize, 32, 16);
  const ballMaterial = new THREE.MeshLambertMaterial();

  sphere = new THREE.Mesh(ballGeo, ballMaterial);
  sphere.castShadow = true;
  sphere.receiveShadow = true;
  sphere.visible = false;
  scene.add(sphere);

  const groundTexture = loader.load("./image/black.png");
  groundTexture.wrapS = groundTexture.wrapT = THREE.RepeatWrapping;
  groundTexture.repeat.set(25, 25);
  groundTexture.anisotropy = 16;
  groundTexture.encoding = THREE.sRGBEncoding;

  const groundMaterial = new THREE.MeshLambertMaterial({ map: groundTexture });

  let mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(20000, 20000),
    groundMaterial
  );
  mesh.position.y = -250;
  mesh.rotation.x = -Math.PI / 2;
  mesh.receiveShadow = true;
  scene.add(mesh);

  const poleGeo = new THREE.BoxGeometry(5, 375, 5);
  const poleMat = new THREE.MeshLambertMaterial();

  mesh = new THREE.Mesh(poleGeo, poleMat);
  mesh.position.x = -125;
  mesh.position.y = -62;
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  scene.add(mesh);

  mesh = new THREE.Mesh(poleGeo, poleMat);
  mesh.position.x = 125;
  mesh.position.y = -62;
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  scene.add(mesh);

  mesh = new THREE.Mesh(new THREE.BoxGeometry(255, 5, 5), poleMat);
  mesh.position.y = -250 + 750 / 2;
  mesh.position.x = 0;
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  scene.add(mesh);

  const gg = new THREE.BoxGeometry(10, 10, 10);
  mesh = new THREE.Mesh(gg, poleMat);
  mesh.position.y = -250;
  mesh.position.x = 125;
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  scene.add(mesh);

  mesh = new THREE.Mesh(gg, poleMat);
  mesh.position.y = -250;
  mesh.position.x = -125;
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  scene.add(mesh);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(window.innerWidth, window.innerHeight);

  container.appendChild(renderer.domElement);

  renderer.outputEncoding = THREE.sRGBEncoding;

  renderer.shadowMap.enabled = true;

  controls = new OrbitControls(camera, renderer.domElement);
  controls.minCameraY = 100;
  controls.maxCameraY = 450;

  controls.minPolarAngle = Math.PI * 0.2;
  controls.maxPolarAngle = Math.PI * 0.45;
  controls.enableZoom = false;
  const fixedDistance = camera.position.distanceTo(controls.target);
  controls.minDistance = fixedDistance;
  controls.maxDistance = fixedDistance;

  controls.addEventListener("start", onControlsStart);
  controls.addEventListener("end", onControlsEnd);

  window.addEventListener("resize", onWindowResize);

  if (TESTING) {
    for (let i = 0; i < 50; i++) {
      simulate(500 - 10 * i);
    }
  }
}

// const MIN_CAMERA_Y = 100

// controls.addEventListener("change", () => {
//   if (camera.position.y < MIN_CAMERA_Y) {
//     camera.position.y = MIN_CAMERA_Y
//   }
// })

// close menu when user try to move
function onControlsStart() {
  const menu = document.getElementById("dynamicMenu");
  const toggleBtn = document.getElementById("menuToggleBtn");
  if (menu && toggleBtn) {
    menu.style.display = "none";
    toggleBtn.style.display = "flex";
  }
}

function onControlsEnd() {
  // Menu stays hidden until user clicks toggle button
}

function onWindowResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();

  renderer.setSize(window.innerWidth, window.innerHeight);
}

function animate(now) {
  requestAnimationFrame(animate);
  simulate(now);
  render();
}

function render() {
  const p = cloth.particles;

  for (let i = 0, il = p.length; i < il; i++) {
    const v = p[i].position;

    clothGeometry.attributes.position.setXYZ(i, v.x, v.y, v.z);
  }

  clothGeometry.attributes.position.needsUpdate = true;

  clothGeometry.computeVertexNormals();

  sphere.position.copy(ballPosition);

  renderer.render(scene, camera);
}

function updateClothTexture(imageUrl) {
  if (!imageUrl || !object) return;

  const newTexture = loader.load(imageUrl);
  newTexture.anisotropy = 16;

  object.material.map = newTexture;
  object.material.needsUpdate = true;

  if (object.customDepthMaterial) {
    object.customDepthMaterial.map = newTexture;
    object.customDepthMaterial.needsUpdate = true;
  }
}

/* ----------------------------- تنظیمات پایه ----------------------------- */
const API_SUBMIT_URL = apiUrl("/api/selection"); // post

// DOM elements
const optionsBtnGroup = document.querySelector(".dynamic-menu-options-btn");
const optionTabButtons =
  optionsBtnGroup?.querySelectorAll("button[data-option]") ?? [];

const optionsListEl = document.getElementById("optionsList");
const saveSubmitBtn = document.getElementById("saveSubmitBtn");
const fabricRecTextEl = document.getElementById("fabricRecText");

// Menu controls
const menuEl = document.getElementById("dynamicMenu");
const menuCloseBtn = document.getElementById("menuCloseBtn");
const menuToggleBtn = document.getElementById("menuToggleBtn");

// AI Modal
const aiModal = document.getElementById("aiModal");
const aiModalBody = document.getElementById("aiModalBody");
const aiModalClose = document.getElementById("aiModalClose");

/* ------------------------------ State ------------------------------ */
const state = {
  activeTab: "fabric",  // fabric | color
  products: [],          // AI-recommended products
  recommendationText: "",
  selection: {
    fabric: null,   // selected product index
    color: null,    // selected variant index
  },
};

/* ------------------------------ Utilities ------------------------------ */
function getUploadId() {
  const params = new URLSearchParams(window.location.search);
  return params.get("upload_id") || "";
}

function setActiveTab(tab) {
  state.activeTab = tab;
  optionTabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.option === tab);
  });
}

function getSelectedProduct() {
  if (state.selection.fabric === null) return null;
  return state.products[state.selection.fabric] || null;
}

function clearList() {
  if (optionsListEl) optionsListEl.innerHTML = "";
}

function renderEmptyState(text = "یک گزینه را انتخاب کنید") {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = text;
  if (optionsListEl) optionsListEl.appendChild(div);
}

function formatFabricPrice(val) {
  if (!val) return "";
  return Number(val).toLocaleString("fa-IR") + " تومان";
}

function getProductUrl(p) {
  if (p.product_url && p.product_url !== "#") return p.product_url;
  if (p.slug) {
    const cfg = window.API_CONFIG || {};
    const shopBase = (cfg.BASE_URL || "").replace(/\/api\/v1\/?$/, "");
    return shopBase + "/products/" + p.slug;
  }
  return "";
}

function getDefaultImage() {
  const cfg = window.API_CONFIG || {};
  const shopBase = (cfg.BASE_URL || "").replace(/\/api\/v1\/?$/, "");
  return shopBase ? shopBase + "/no-image-product.png" : "";
}

function makeOptionCard({ id, fa, image, isSelected, onClick, price }) {
  const card = document.createElement("div");
  card.className = "dynamic-menu-option-item";
  if (isSelected) card.classList.add("selected");

  const thumbWrap = document.createElement("div");
  thumbWrap.className = "thumb-wrapper";
  const thumb = document.createElement("img");
  thumb.className = "thumb";
  thumb.loading = "lazy";
  thumb.src = image || getDefaultImage();
  thumb.alt = fa || id || "";

  const label = document.createElement("div");
  label.className = "option-label";
  label.textContent = fa || id || "";

  thumbWrap.appendChild(thumb);
  card.appendChild(thumbWrap);
  card.appendChild(label);

  if (price) {
    const priceEl = document.createElement("div");
    priceEl.className = "option-price";
    priceEl.textContent = price;
    card.appendChild(priceEl);
  }

  card.addEventListener("click", () => onClick?.({ id, fa, image, card }));
  return card;
}

/* -------------- Extract color variants from a product -------------- */
function getProductColors(product) {
  const variants = product.variants || [];
  const colors = [];
  const seen = new Set();

  for (const v of variants) {
    const attrs = v.attributes || {};
    for (const [groupName, attrVal] of Object.entries(attrs)) {
      if (groupName.includes("رنگ") || groupName.toLowerCase().includes("color")) {
        if (!seen.has(attrVal) && v.in_stock !== false) {
          seen.add(attrVal);
          colors.push({
            id: attrVal,
            fa: attrVal,
            image: product.image || getDefaultImage(),
            variant: v,
          });
        }
      }
    }
  }

  return colors;
}

/* ---------------------------- Render Tabs ---------------------------- */
function renderFabricTab() {
  clearList();
  const products = state.products;
  if (!products.length) return renderEmptyState("محصولی یافت نشد!");

  products.forEach((p, idx) => {
    const isSelected = state.selection.fabric === idx;
    const price = formatFabricPrice(p.price);
    const img = p.image || getDefaultImage();
    const card = makeOptionCard({
      id: idx,
      fa: p.title || p.name_fa || "پارچه",
      image: img,
      isSelected,
      price,
      onClick: () => {
        state.selection.fabric = idx;
        state.selection.color = null;

        // Show this fabric on the cloth immediately
        updateClothTexture(img);

        // Auto-switch to color tab
        setActiveTab("color");
        renderColorTab();
      },
    });
    optionsListEl.appendChild(card);
  });
}

function renderColorTab() {
  clearList();
  const product = getSelectedProduct();
  if (!product) {
    renderEmptyState("لطفاً ابتدا یک پارچه انتخاب کنید.");
    return;
  }

  const colors = getProductColors(product);
  if (!colors.length) {
    renderEmptyState("رنگ‌بندی موجود نیست.");
    return;
  }

  colors.forEach((col, idx) => {
    const isSelected = state.selection.color === idx;
    const card = makeOptionCard({
      id: idx,
      fa: col.fa,
      image: col.image,
      isSelected,
      onClick: ({ card, image }) => {
        // Deselect all, then select this
        [...optionsListEl.querySelectorAll(".dynamic-menu-option-item.selected")]
          .forEach((el) => el.classList.remove("selected"));
        state.selection.color = idx;
        card.classList.add("selected");

        // Update cloth texture with the color variant image
        updateClothTexture(image);

        // Hide menu after selection
        menuEl.style.display = "none";
        menuToggleBtn.style.display = "flex";
      },
    });
    optionsListEl.appendChild(card);
  });
}

/* -------------------------- Tab Switcher -------------------------- */
optionTabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.option; // fabric | color
    setActiveTab(tab);
    if (tab === "fabric") renderFabricTab();
    else renderColorTab();
  });
});

/* -------------------- Load AI Recommendations -------------------- */
async function loadRecommendations() {
  const uploadId = getUploadId();
  if (!uploadId) {
    renderEmptyState("شناسه آپلود یافت نشد.");
    return;
  }

  // Check sessionStorage for pre-fetched data from processing screen
  let data = null;
  try {
    const cached = sessionStorage.getItem("fabric_recommendations");
    if (cached) {
      data = JSON.parse(cached);
      sessionStorage.removeItem("fabric_recommendations");
    }
  } catch (e) { /* ignore */ }

  if (!data) {
    // Fetch from API
    const headers = { "Content-Type": "application/json" };
    const token = localStorage.getItem("auth_token");
    if (token) headers["Authorization"] = "Bearer " + token;

    try {
      const res = await fetch(apiUrl("/recommendations", "secondary"), {
        method: "POST",
        headers,
        body: JSON.stringify({ upload_id: uploadId }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      data = await res.json();
    } catch (err) {
      console.error("Failed to load recommendations:", err);
      renderEmptyState("خطا در دریافت پیشنهادات. لطفاً صفحه را رفرش کنید.");
      return;
    }
  }

  // Populate state
  state.products = data.products || [];
  state.recommendationText = data.recommendations_text || "";

  // Show recommendation text in menu header
  if (state.recommendationText && fabricRecTextEl) {
    fabricRecTextEl.textContent = state.recommendationText;
    fabricRecTextEl.style.display = "block";
  }

  // Show menu and render fabric tab
  if (menuEl) menuEl.style.display = "flex";
  if (menuToggleBtn) menuToggleBtn.style.display = "none";
  setActiveTab("fabric");
  renderFabricTab();
}

/* ---------------------- Submit Selection ---------------------- */
saveSubmitBtn?.addEventListener("click", async () => {
  const product = getSelectedProduct();
  if (!product) {
    alert("لطفاً ابتدا یک پارچه انتخاب کنید.");
    return;
  }

  const colors = getProductColors(product);
  const selectedColor = state.selection.color !== null ? colors[state.selection.color] : null;

  const payload = {
    upload_id: getUploadId(),
    fabric: {
      id: product.id || product.slug,
      title: product.title,
      slug: product.slug,
    },
    color: selectedColor ? {
      id: selectedColor.id,
      fa: selectedColor.fa,
    } : null,
  };

  try {
    const res = await fetch(API_SUBMIT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("ارسال ناموفق بود");
    const data = await res.json().catch(() => ({}));
    console.log("ارسال به بک‌اند:", data);
    alert("انتخاب‌ها با موفقیت ثبت و ارسال شد.");
  } catch (err) {
    console.error(err);
    alert("مشکلی در ارسال به سرور پیش آمد.");
  }
});

/* -------------------- AI Modal (detail view) -------------------- */
function openAIModal() {
  if (!aiModalBody) return;
  aiModalBody.innerHTML = "";

  if (!state.products.length) {
    aiModalBody.innerHTML = '<div class="empty-state">پیشنهادی موجود نیست.</div>';
    aiModal.style.display = "flex";
    return;
  }

  // Show recommendation text
  if (state.recommendationText) {
    const textDiv = document.createElement("div");
    textDiv.className = "ai-rec-text";
    textDiv.textContent = state.recommendationText;
    aiModalBody.appendChild(textDiv);
  }

  // Product cards
  const heading = document.createElement("h3");
  heading.style.cssText = "margin: 16px 0 12px; font-size: 16px; color: #333;";
  heading.textContent = "پارچه‌های پیشنهادی";
  aiModalBody.appendChild(heading);

  const grid = document.createElement("div");
  grid.className = "ai-products-grid";

  state.products.forEach((p) => {
    const card = document.createElement("div");
    card.className = "ai-product-card";

    const name = p.title || p.name_fa || "پارچه";
    const img = p.image || getDefaultImage();
    const price = formatFabricPrice(p.price);
    const productUrl = getProductUrl(p);

    let html = `<img src="${img}" alt="${name}" />`;
    html += `<div class="ai-p-name">${name}</div>`;
    if (price) html += `<div class="ai-p-price">${price}</div>`;
    if (p.brand) html += `<div style="font-size:11px;color:#888;margin-top:2px;">${p.brand}</div>`;
    html += `<button class="ai-p-preview-btn" data-img="${img}">نمایش روی پرچم</button>`;
    if (productUrl) html += `<a href="${productUrl}" target="_blank" class="ai-p-link">مشاهده محصول</a>`;

    card.innerHTML = html;

    const previewBtn = card.querySelector(".ai-p-preview-btn");
    if (previewBtn) {
      previewBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        updateClothTexture(previewBtn.dataset.img);
        closeAIModal();
      });
    }

    const cardImg = card.querySelector("img");
    if (cardImg) {
      cardImg.style.cursor = "pointer";
      cardImg.addEventListener("click", (e) => {
        e.stopPropagation();
        updateClothTexture(img);
        closeAIModal();
      });
    }

    grid.appendChild(card);
  });

  aiModalBody.appendChild(grid);
  aiModal.style.display = "flex";
}

function closeAIModal() {
  if (aiModal) aiModal.style.display = "none";
}

aiModalClose?.addEventListener("click", closeAIModal);
aiModal?.addEventListener("click", (e) => {
  if (e.target === aiModal) closeAIModal();
});

/* ---------------------- Menu show/hide ---------------------- */
function hideMenu() {
  if (!menuEl) return;
  menuEl.style.display = "none";
  if (menuToggleBtn) menuToggleBtn.style.display = "flex";
}

function showMenu() {
  if (!menuEl) return;
  menuEl.style.display = "flex";
  if (menuToggleBtn) menuToggleBtn.style.display = "none";
}

menuCloseBtn?.addEventListener("click", hideMenu);
menuToggleBtn?.addEventListener("click", showMenu);

/* -------------------- OrbitControls integration ------------------- */
window.attachOrbitControls = function (controls) {
  if (!controls) return;
  controls.addEventListener("start", hideMenu);
  if (controls?.domElement) {
    const el = controls.domElement;
    const onInteract = () => hideMenu();
    el.addEventListener("pointerdown", onInteract);
    el.addEventListener("wheel", onInteract, { passive: true });
  }
};

/* ------------------------------- Init ------------------------------- */
loadRecommendations().catch((err) => {
  console.error("خطا در بارگذاری پیشنهادات:", err);
  clearList();
  renderEmptyState("مشکل در دریافت داده‌ها. لطفاً دوباره تلاش کنید.");
});
