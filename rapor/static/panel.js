(() => {
  const api = (p, q = {}) => `/api/${p}?` + new URLSearchParams(q);
  const toLogin = () => { location.href = "/giris?hata=3"; };
  const tl = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });
  const fmtTL = v => (v < 0 ? "−" : "") + tl.format(Math.abs(v)) + " ₺";
  const fmtDay = iso => { const [y, m, d] = iso.split("-"); return `${d}.${m}.${y}`; };
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let state = { bas: null, bit: null, days: 28, data: null, sort: { k: "net", dir: -1 } };
  let chart;

  function showError(msg) { const b = $("errbox"); b.textContent = msg; b.style.display = msg ? "block" : "none"; }

  async function load() {
    const q = {};
    if (state.bas) q.bas = state.bas;
    if (state.bit) q.bit = state.bit;
    try {
      const r = await fetch(api("ozet", q));
      if (r.status === 401) return toLogin();
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Veri alınamadı");
      showError("");
      state.data = j;
      render(j);
    } catch (e) { showError(e.message); }
  }

  function render(d) {
    $("demobar").hidden = !d.demo;
    document.querySelector(".upload-card").hidden = !!d.demo;
    const v = d.veri, a = d.aralik;
    const ageDays = Math.round((Date.now() - new Date(v.son_gun + "T23:59:59")) / 864e5);
    $("fresh").innerHTML = `Veri <b>${esc(v.son_siparis)}</b> tarihli son siparişe kadar · dosya ${esc(v.dosya_zamani)}` +
      (ageDays > 7 ? ` · <span class="stale">${ageDays} gündür yeni veri yok</span>` : "");
    $("bas").value = a.bas; $("bit").value = a.bit;
    $("bas").min = $("bit").min = v.ilk_gun; $("bas").max = $("bit").max = v.son_gun;
    $("rangenote").textContent = `${a.gun} gün; önceki dönem ${fmtDay(a.onceki_bas)} – ${fmtDay(a.onceki_bit)} ile karşılaştırılıyor`;

    $("kpis").innerHTML = d.kpi.map((k, i) => `
      <div class="card kpi${i === 0 ? " hero" : ""}">
        <div class="lbl">${esc(k.ad)}</div>
        <div class="val">${esc(k.deger)}</div>
        <div class="d">${k.degisim ? `<span class="${k.yon}">${esc(k.degisim)}</span> · ` : ""}önceki ${esc(k.onceki)}</div>
      </div>`).join("");

    $("alerts").innerHTML = d.uyarilar.length ? d.uyarilar.map(u => `
      <div class="alert ${esc(u.seviye)}"><span class="tag">${esc(u.etiket)}</span><b>${esc(u.baslik)}</b><p>${esc(u.ayrinti)}</p></div>`).join("")
      : `<div class="empty">Bu dönem için uyarı yok.</div>`;

    drawChart(d.gunluk);
    drawTable();

    const q = v.kalite.length ? `<ul>${v.kalite.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : "";
    $("foot").innerHTML = `Net kâr = brüt satış − komisyon − kargo − ürün maliyeti; KDV ve reklam gideri dahil değil. ` +
      `İade oranı ve stok süresi seçilen dönemin son 28 gününe göre. Dosya: ${esc(v.siparis_dosyasi)}.${q}`;
  }

  function drawChart(rows) {
    const labels = rows.map(r => r.gun.slice(8, 10) + "." + r.gun.slice(5, 7));
    const data = rows.map(r => r.net);
    const ink2 = css("--ink2"), line = css("--line"), bar = css("--bar");
    const cfg = {
      type: "bar",
      data: { labels, datasets: [{ label: "Net kâr", data, backgroundColor: bar, borderRadius: 3,
        borderSkipped: "start", maxBarThickness: 28, categoryPercentage: 0.85, barPercentage: 0.9 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 200 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            title: items => fmtDay(rows[items[0].dataIndex].gun),
            label: it => {
              const r = rows[it.dataIndex];
              return [`Net kâr: ${fmtTL(r.net)}`, `Brüt satış: ${fmtTL(r.brut)}`, `Sipariş: ${r.siparis}`];
            } } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: ink2, maxRotation: 0, autoSkipPadding: 10 } },
          y: { grid: { color: line }, border: { display: false }, ticks: { color: ink2, callback: fmtTL, maxTicksLimit: 6 } },
        },
      },
    };
    if (chart) chart.destroy();
    chart = new Chart($("chart"), cfg);
  }

  function drawTable() {
    const { k, dir } = state.sort;
    const rows = [...state.data.urunler].sort((a, b) => {
      const x = a[k], y = b[k];
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(y, "tr") : x - y) * dir;
    });
    const n = v => v == null ? "—" : tl.format(v);
    const p = v => v == null ? "—" : "%" + (v * 100).toLocaleString("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    document.querySelector("#tbl tbody").innerHTML = rows.map(r => `<tr>
      <td>${esc(r.urun)}</td><td>${n(r.adet)}</td><td>${fmtTL(r.brut)}</td>
      <td class="${r.net < 0 ? "neg" : ""}">${fmtTL(r.net)}</td><td>${p(r.iade)}</td>
      <td>${n(r.stok)}</td><td class="${r.gun_yeter != null && r.gun_yeter < 7 ? "low" : ""}">${n(r.gun_yeter)}</td></tr>`).join("");
    document.querySelectorAll("#tbl th").forEach(th => th.setAttribute("aria-sort",
      th.dataset.k === k ? (dir > 0 ? "ascending" : "descending") : "none"));
  }

  document.querySelectorAll("#tbl th").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k;
    state.sort = { k, dir: state.sort.k === k ? -state.sort.dir : (k === "urun" ? 1 : -1) };
    drawTable();
  }));

  document.querySelectorAll("#presets button").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll("#presets button").forEach(x => x.setAttribute("aria-pressed", x === b));
    const end = state.data ? state.data.veri.son_gun : null;
    state.days = +b.dataset.days;
    if (end) {
      const s = new Date(end + "T00:00:00Z"); s.setUTCDate(s.getUTCDate() - state.days + 1);
      state.bas = s.toISOString().slice(0, 10); state.bit = end;
    }
    load();
  }));

  ["bas", "bit"].forEach(id => $(id).addEventListener("change", () => {
    state.bas = $("bas").value; state.bit = $("bit").value;
    document.querySelectorAll("#presets button").forEach(x => x.setAttribute("aria-pressed", "false"));
    load();
  }));

  document.querySelectorAll(".upload form").forEach(f => f.addEventListener("submit", async ev => {
    ev.preventDefault();
    const msg = f.querySelector(".msg"), btn = f.querySelector("button");
    const fd = new FormData(f); fd.append("tur", f.dataset.tur);
    btn.disabled = true; msg.className = "msg"; msg.textContent = "Yükleniyor…";
    try {
      const r = await fetch(api("yukle"), { method: "POST", body: fd });
      if (r.status === 401) return toLogin();
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Yüklenemedi");
      msg.className = "msg ok"; msg.textContent = j.mesaj; f.reset();
      state.bas = state.bit = null; load();
    } catch (e) { msg.className = "msg err"; msg.textContent = e.message; }
    finally { btn.disabled = false; }
  }));

  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => state.data && drawChart(state.data.gunluk));
  load();
})();
