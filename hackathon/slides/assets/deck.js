// Minimal slide engine: ←/→/space/PgUp/PgDn navigate, Home/End jump,
// N toggles speaker notes, O toggles the overview grid, A jumps to the appendix, I goes back to the index,
// F toggles fullscreen. The URL hash (#12) tracks the current slide.
(function () {
  const stage = document.getElementById("stage");
  const slides = Array.from(stage.querySelectorAll(".slide"));
  const deckTitle = document.body.dataset.title || document.title;
  const footLogo = document.body.dataset.logo || "assets/prometheus_logo.png";
  const indexHref = document.body.dataset.index; // set by the build for decks that have an index to link to
  let cur = 0;

  // Talk (and bonus) slides are numbered on their own; appendix slides get "A n / m".
  const main = slides.filter((s) => !s.classList.contains("appendix"));
  const appx = slides.filter((s) => s.classList.contains("appendix"));
  slides.forEach((s) => {
    if (s.classList.contains("title") || s.dataset.nofoot !== undefined) return;
    const inAppx = s.classList.contains("appendix");
    const num = inAppx ? `A ${appx.indexOf(s) + 1} / ${appx.length}` : `${main.indexOf(s) + 1} / ${main.length}`;
    const f = document.createElement("div");
    f.className = "foot";
    const right = indexHref
      ? `<span class="fr"><a class="idx" href="${indexHref}">All decks</a><span>${num}</span></span>`
      : `<span>${num}</span>`;
    f.innerHTML = `<span class="fl"><img src="${footLogo}" alt=""><span>${deckTitle}</span></span>${right}`;
    s.appendChild(f);
  });

  const progress = Object.assign(document.createElement("div"), { id: "progress" });
  const counter = Object.assign(document.createElement("div"), { id: "counter" });
  const notes = Object.assign(document.createElement("div"), { id: "notes" });
  const overview = Object.assign(document.createElement("div"), { id: "overview" });
  document.body.append(progress, counter, notes, overview);

  slides.forEach((s, i) => {
    const t = document.createElement("div");
    t.className = "thumb";
    const h = s.querySelector("h1, h2");
    t.innerHTML = `<b>${s.classList.contains("appendix") ? "Appendix · " : ""}${i + 1}</b>${h ? h.textContent : "(untitled)"}`;
    t.onclick = () => { document.body.classList.remove("overview"); go(i); };
    overview.appendChild(t);
  });

  // Grow each slide's .content (CSS zoom, capped) until it fills the space above
  // the footer, so sparse slides don't leave an empty lower third. Dense slides
  // are shrunk slightly if they would overflow. Opt out with data-nofit.
  const SAFE_BOTTOM = 842, MAX_ZOOM = 1.45, MIN_ZOOM = 0.8;
  function overflows(slide, c) {
    const top = slide.getBoundingClientRect().top;
    if (c.getBoundingClientRect().bottom - top > SAFE_BOTTOM) return true;
    for (const el of c.querySelectorAll("pre, .box, td, .card, .col, .grid > *")) {
      if (el.scrollWidth > el.clientWidth + 1) return true;
    }
    return c.scrollWidth > c.clientWidth + 1;
  }
  function autofit() {
    const prev = stage.style.transform;
    stage.style.transform = "none";
    slides.forEach((s) => {
      const c = s.querySelector(":scope > .content");
      if (!c || s.dataset.nofit !== undefined) return;
      const wasActive = s.classList.contains("active");
      s.style.visibility = "visible";
      c.style.flex = "none";
      let lo = MIN_ZOOM, hi = MAX_ZOOM;
      c.style.zoom = 1;
      if (!overflows(s, c)) lo = 1; else hi = 1;
      for (let i = 0; i < 9; i++) {
        const mid = (lo + hi) / 2;
        c.style.zoom = mid;
        if (overflows(s, c)) hi = mid; else lo = mid;
      }
      c.style.zoom = lo;
      c.style.flex = "";
      s.style.visibility = wasActive ? "" : "";
    });
    stage.style.transform = prev;
  }

  function fit() {
    const k = Math.min(window.innerWidth / 1600, window.innerHeight / 900);
    stage.style.transform = `scale(${k})`;
  }
  function go(i) {
    cur = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach((s, j) => s.classList.toggle("active", j === cur));
    progress.style.width = `${((cur + 1) / slides.length) * 100}%`;
    counter.textContent = `${cur + 1} / ${slides.length}`;
    const n = slides[cur].querySelector("aside.notes");
    notes.innerHTML = n ? n.innerHTML : "<i>No notes for this slide.</i>";
    history.replaceState(null, "", `#${cur + 1}`);
  }
  window.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (["ArrowRight", "PageDown", " ", "ArrowDown"].includes(k)) { e.preventDefault(); go(cur + 1); }
    else if (["ArrowLeft", "PageUp", "ArrowUp", "Backspace"].includes(k)) { e.preventDefault(); go(cur - 1); }
    else if (k === "Home") go(0);
    else if (k === "End") go(slides.length - 1);
    else if (k === "n" || k === "N") document.body.classList.toggle("show-notes");
    else if (k === "o" || k === "O") document.body.classList.toggle("overview");
    else if (k === "a" || k === "A") { const j = slides.findIndex((x) => x.classList.contains("appendix")); if (j >= 0) go(j); }
    else if (k === "i" || k === "I") location.href = "index.html";
    else if (k === "f" || k === "F") {
      if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen();
    }
  });
  stage.addEventListener("click", (e) => {
    if (e.target.closest("a, pre, code, table")) return;
    go(cur + (e.clientX > window.innerWidth / 2 ? 1 : -1));
  });
  window.addEventListener("resize", fit);
  autofit();
  document.fonts.ready.then(() => { autofit(); fit(); });
  fit();
  go((parseInt(location.hash.slice(1), 10) || 1) - 1);
  window.__deck = { go, count: slides.length };
})();
