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
const TAXONOMY_URL = "./taxonomy.fa.v2.json"; // get
const API_SUBMIT_URL = apiUrl("/api/selection"); // post

// عناصر DOM مطابق index.html و style.css
const optionsBtnGroup = document.querySelector(".dynamic-menu-options-btn");
const optionTabButtons =
  optionsBtnGroup?.querySelectorAll("button[data-option]") ?? [];

const optionsListEl = document.getElementById("optionsList");
const displayBtn = document.getElementById("displayBtn");
const saveSubmitBtn = document.getElementById("saveSubmitBtn");
const showAIsuggestionBtn = document.getElementById("showAIsuggestion");

// منو و کنترل‌های نمایش/مخفی
const menuEl = document.getElementById("dynamicMenu");
const menuCloseBtn = document.getElementById("menuCloseBtn");
const menuToggleBtn = document.getElementById("menuToggleBtn");

// مودال پیشنهادات هوش مصنوعی
const aiModal = document.getElementById("aiModal");
const aiModalBody = document.getElementById("aiModalBody");
const aiModalClose = document.getElementById("aiModalClose");

// اعلان هشدار بالای صفحه (اختیاری - اگر خواستید قابلیت بستن اضافه کنید)
const warningNotice = document.getElementById("warningNotice");

/* ------------------------------ وضعیت برنامه ------------------------------ */
const state = {
  // تب‌ها: category | material | color
  activeTab: "category",

  // داده‌ی جیسون بک‌اند
  data: null, // { taxonomy: { categories: [...] }, ai_recommendations: {...} }

  // انتخاب‌های کاربر (تک‌گزینه‌ای)
  selection: {
    category: null, // category.id
    fabric: null, // fabric.id (زیرمجموعه‌ی category)
    color: null, // color.id (زیرمجموعه‌ی fabric)
  },
};

/* ------------------------------ یوتیلیتی‌ها ------------------------------ */
function setActiveTab(tab) {
  state.activeTab = tab;
  optionTabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.option === tab);
  });
}

function getSelectedCategory() {
  if (!state.selection.category) return null;
  return state.data?.taxonomy?.categories?.find(
    (c) => c.id === state.selection.category
  );
}

function getSelectedFabric() {
  const cat = getSelectedCategory();
  if (!cat || !state.selection.fabric) return null;
  return cat.fabrics?.find((f) => f.id === state.selection.fabric) ?? null;
}

function clearList() {
  optionsListEl.innerHTML = "";
}

function renderEmptyState(text = "یک گزینه را انتخاب کنید") {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = text;
  optionsListEl.appendChild(div);
}

function makeOptionCard({ id, fa, image, isSelected, onClick }) {
  const card = document.createElement("div");
  card.className = "dynamic-menu-option-item";
  if (isSelected) card.classList.add("selected");

  const thumbWrap = document.createElement("div");
  thumbWrap.className = "thumb-wrapper";
  const thumb = document.createElement("img");
  thumb.className = "thumb";
  thumb.loading = "lazy";
  thumb.src = image || "";
  thumb.alt = fa || id || "";

  const label = document.createElement("div");
  label.className = "option-label";
  label.textContent = fa || id || "";

  thumbWrap.appendChild(thumb);
  card.appendChild(thumbWrap);
  card.appendChild(label);

  card.addEventListener("click", () => onClick?.({ id, fa, image, card }));
  return card;
}

/* ---------------------------- رندر هر تب ---------------------------- */
function renderCategoryTab() {
  clearList();
  const cats = state.data?.taxonomy?.categories ?? [];
  if (!cats.length) return renderEmptyState("دسته‌ای یافت نشد!");

  cats.forEach((cat) => {
    const isSelected = state.selection.category === cat.id;
    const card = makeOptionCard({
      id: cat.id,
      fa: cat.fa,
      image: cat.image,
      isSelected,
      onClick: ({ id }) => {
        state.selection.category = id;
        // با تغییر دسته، جنس و رنگ ریست می‌شوند
        state.selection.fabric = null;
        state.selection.color = null;

        // بلافاصله به تب جنس برو
        setActiveTab("material");
        renderMaterialTab();
      },
    });
    optionsListEl.appendChild(card);
  });
}

function renderMaterialTab() {
  clearList();
  const cat = getSelectedCategory();
  if (!cat) {
    renderEmptyState("لطفاً ابتدا «دسته‌بندی» را انتخاب کنید.");
    return;
  }
  const fabrics = cat.fabrics ?? [];
  if (!fabrics.length) return renderEmptyState("پارچه‌ای یافت نشد!");

  fabrics.forEach((fab) => {
    const isSelected = state.selection.fabric === fab.id;
    const card = makeOptionCard({
      id: fab.id,
      fa: fab.fa,
      image: fab.image,
      isSelected,
      onClick: ({ id }) => {
        state.selection.fabric = id;
        state.selection.color = null; // با تغییر جنس، رنگ ریست شود
        // بلافاصله به تب رنگ برو
        setActiveTab("color");
        renderColorTab();
      },
    });
    optionsListEl.appendChild(card);
  });
}

function renderColorTab() {
  clearList();
  const fabric = getSelectedFabric();
  if (!fabric) {
    renderEmptyState("لطفاً ابتدا «جنس» را انتخاب کنید.");
    return;
  }
  const colors = fabric.colors ?? [];
  if (!colors.length) return renderEmptyState("رنگی یافت نشد!");

  colors.forEach((col) => {
    const isSelected = state.selection.color === col.id;
    const card = makeOptionCard({
      id: col.id,
      fa: col.fa,
      image: col.image,
      isSelected,
      onClick: ({ id, card, image }) => {
        // تک‌گزینه‌ای: ابتدا همه کارت‌های انتخاب‌شده را پاک کن
        [
          ...optionsListEl.querySelectorAll(
            ".dynamic-menu-option-item.selected"
          ),
        ].forEach((el) => el.classList.remove("selected"));
        state.selection.color = id;
        card.classList.add("selected");
        updateClothTexture(image);
        menuEl.style.display = "none";
        menuToggleBtn.style.display = "flex";
      },
    });
    optionsListEl.appendChild(card);
  });
}

/* -------------------------- سوییچر تب‌ها -------------------------- */
optionTabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.option; // category | material | color
    setActiveTab(tab);
    if (tab === "category") renderCategoryTab();
    else if (tab === "material") renderMaterialTab();
    else renderColorTab();
  });
});

/* -------------------------- بارگذاری جیسون -------------------------- */
async function loadTaxonomy() {
  const res = await fetch(TAXONOMY_URL, { cache: "no-store" });
  if (!res.ok) throw new Error("خطا در دریافت داده");
  const data = await res.json();
  // انتظار ساختار { schema_version, locale, taxonomy: { categories: [...] }, ai_recommendations: {...} }
  state.data = data;
  setActiveTab("category");
  renderCategoryTab();
}

/* ---------------------------- نمایش/ارسال ---------------------------- */
function getSelectionPayload() {
  const { category, fabric, color } = state.selection;

  // علاوه بر id، نسخه‌ی فارسی را هم از داده استخراج می‌کنیم
  const cat = state.data?.taxonomy?.categories?.find((c) => c.id === category);
  const fab = cat?.fabrics?.find((f) => f.id === fabric);
  const col = fab?.colors?.find((c) => c.id === color);

  return {
    category: category ? { id: category, fa: cat?.fa ?? "" } : null,
    fabric: fabric ? { id: fabric, fa: fab?.fa ?? "" } : null,
    color: color ? { id: color, fa: col?.fa ?? "" } : null,
  };
}

// displayBtn?.addEventListener("click", () => {
//   const payload = getSelectionPayload();
//   console.log("Selection to display:", payload);
//   const cat = payload.category?.fa ?? "—";
//   const fab = payload.fabric?.fa ?? "—";
//   const col = payload.color?.fa ?? "—";
//   alert(`انتخاب فعلی:\nدسته‌بندی: ${cat}\nجنس: ${fab}\nرنگ: ${col}`);
// });

saveSubmitBtn?.addEventListener("click", async () => {
  const payload = getSelectionPayload();

  if (!payload.category || !payload.fabric || !payload.color) {
    alert("لطفاً هر سه مورد «دسته‌بندی»، «جنس» و «رنگ» را انتخاب کنید.");
    return;
  }

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

/* ------------------------ پیشنهادات هوش مصنوعی ------------------------ */
function openAIModal() {
  // پرکردن بدنه مودال از ai_recommendations
  aiModalBody.innerHTML = "";
  const recs = state.data?.ai_recommendations?.recommendations ?? [];
  if (!recs.length) {
    const d = document.createElement("div");
    d.className = "empty-state";
    d.textContent = "پیشنهادی موجود نیست.";
    aiModalBody.appendChild(d);
  } else {
    recs.forEach((rec) => {
      const item = document.createElement("div");
      item.className = "ai-suggestion-item";

      const title = document.createElement("div");
      title.className = "ai-suggestion-title";
      title.textContent = rec.title_fa || "پیشنهاد";

      const text = document.createElement("div");
      text.className = "ai-suggestion-text";
      text.textContent = rec.text_fa || "";

      const tags = document.createElement("div");
      tags.className = "ai-suggestion-details";

      const mkTag = (label) => {
        const el = document.createElement("span");
        el.className = "ai-suggestion-tag";
        el.textContent = label;
        return el;
      };

      if (rec.category?.fa) tags.appendChild(mkTag(`دسته:${rec.category.fa}`));
      if (rec.fabric?.fa) tags.appendChild(mkTag(`جنس:${rec.fabric.fa}`));
      if (rec.color?.fa) tags.appendChild(mkTag(`رنگ:${rec.color.fa}`));

      item.appendChild(title);
      item.appendChild(text);
      item.appendChild(tags);

      item.addEventListener("click", () => {
        // اعمال پیشنهاد
        state.selection.category = rec.category?.id ?? null;
        state.selection.fabric = rec.fabric?.id ?? null;
        state.selection.color = rec.color?.id ?? null;

        // let colorImage = null;
        //   if(state.data && rec.category?.id && rec.fabric?.id && rec.color?.id ){
        //   const category = state.data.categories?.find((c)=> c.id === rec.category.id)
        //   if(category){
        //     const fabric = category.fabrics?.find((f)=> f.id === rec.fabric.id)
        //     if(fabric){
        //       const color = fabric.color?.find((c)=> c.id === rec.color.id)
        //         if(color && color.image){
        //           colorImage = color.image
        //         }
        //       }
        //     }
        //   }

        //   if(colorImage){
        //     updateClothTexture(colorImage)
        //   }
        updateClothTexture(rec.color.image);

        // رفتن به تب رنگ و رندر همان تب (آخرین مرحله)
        setActiveTab("color");
        renderColorTab();

        // بستن مودال
        closeAIModal();
      });

      aiModalBody.appendChild(item);
    });
  }

  aiModal.style.display = "flex";
}

function closeAIModal() {
  aiModal.style.display = "none";
}

showAIsuggestionBtn?.addEventListener("click", openAIModal);
aiModalClose?.addEventListener("click", closeAIModal);
aiModal?.addEventListener("click", (e) => {
  if (e.target === aiModal) closeAIModal();
});

/* ---------------------- مخفی/نمایش منو (UI موجود) ---------------------- */
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

/* -------------------- اتصال به OrbitControls (اختیاری) ------------------- */
window.attachOrbitControls = function (controls) {
  if (!controls) return;
  controls.addEventListener("start", hideMenu);
  // when change end show it again
  // controls.addEventListener("end", showMenu);
  if (controls?.domElement) {
    const el = controls.domElement;
    const onInteract = () => hideMenu();
    el.addEventListener("pointerdown", onInteract);
    el.addEventListener("wheel", onInteract, { passive: true });
  }
};

/* ------------------------------- شروع کار ------------------------------- */
loadTaxonomy().catch((err) => {
  console.error("خطا در بارگذاری taxonomy:", err);
  clearList();
  renderEmptyState("مشکل در دریافت داده‌ها. لطفاً دوباره تلاش کنید.");
});

setTimeout(() => {
  const warningNotice = document.getElementById("warningNotice");
  if (warningNotice && !warningNotice.classList.contains("hidden")) {
    warningNotice.classList.add("hidden");
  }
}, 5000);
