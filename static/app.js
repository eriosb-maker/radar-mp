/* ─── Estado global ─────────────────────────────────────────────── */
const state = {
  rut: localStorage.getItem("radar_rut") || null,
  paginaLic: 0,
  limitLic: 50,
  scoreMin: 40,
  organismoFiltro: "",
};

const REGIONES = [
  "Arica y Parinacota","Tarapacá","Antofagasta","Atacama","Coquimbo",
  "Valparaíso","Metropolitana","O'Higgins","Maule","Ñuble","Biobío",
  "La Araucanía","Los Ríos","Los Lagos","Aysén","Magallanes",
];

/* ─── Utilidades ────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const fmt = n => n != null ? `$ ${Number(n).toLocaleString("es-CL")} CLP` : "No informado";
const fmtFecha = iso => iso ? new Date(iso).toLocaleDateString("es-CL", { day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit" }) : "—";
const horasRestantes = iso => iso ? Math.round((new Date(iso) - Date.now()) / 3_600_000) : null;
const scoreClass = s => s >= 75 ? "score-alto" : s >= 55 ? "score-medio" : "score-bajo";

async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || "Error en el servidor");
  }
  return r.json();
}

/* ─── Navegación ────────────────────────────────────────────────── */
document.querySelectorAll(".nav-item").forEach(el => {
  el.addEventListener("click", e => {
    e.preventDefault();
    const view = el.dataset.view;
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    el.classList.add("active");
    $(`view-${view}`).classList.add("active");

    if (view === "dashboard")    loadDashboard();
    if (view === "oportunidades") loadOportunidades();
    if (view === "licitaciones") { state.paginaLic = 0; loadLicitaciones(); }
  });
});

/* ─── Sesión / RUT ───────────────────────────────────────────────── */
function setRut(rut) {
  state.rut = rut;
  localStorage.setItem("radar_rut", rut);
  $("rut-badge").textContent = rut;
}

if (state.rut) $("rut-badge").textContent = state.rut;

/* ─── DASHBOARD ─────────────────────────────────────────────────── */
async function loadDashboard() {
  try {
    const stats = await api("/stats");
    $("stat-activas").textContent    = stats.licitaciones_activas.toLocaleString("es-CL");
    $("stat-total").textContent      = stats.licitaciones_total.toLocaleString("es-CL");
    $("stat-proveedores").textContent = stats.proveedores.toLocaleString("es-CL");
    $("stat-oport").textContent      = stats.oportunidades_hoy.toLocaleString("es-CL");
  } catch(e) { console.error(e); }

  if (state.rut) {
    try {
      const data = await api(`/oportunidades/${state.rut}?limit=5&score_min=60`);
      renderOportunidades("top-oportunidades", data.oportunidades);
    } catch(_) {}
  }
}

/* ─── OPORTUNIDADES ─────────────────────────────────────────────── */
async function loadOportunidades() {
  if (!state.rut) {
    $("lista-oportunidades").innerHTML = '<div class="empty-state">Registra tu RUT en Mi Perfil.</div>';
    return;
  }
  try {
    const data = await api(`/oportunidades/${state.rut}?limit=100&score_min=${state.scoreMin}`);
    renderOportunidades("lista-oportunidades", data.oportunidades);
  } catch(e) {
    $("lista-oportunidades").innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}

function renderOportunidades(containerId, items) {
  const el = $(containerId);
  if (!items || items.length === 0) {
    el.innerHTML = '<div class="empty-state">No hay oportunidades para los filtros actuales.</div>';
    return;
  }
  el.innerHTML = items.map(op => {
    const l = op.licitacion;
    const horas = horasRestantes(l.fecha_cierre);
    const urgente = horas !== null && horas > 0 && horas < 48;
    return `
    <div class="oport-card" onclick="abrirModal(${JSON.stringify(op).replace(/"/g,'&quot;')})">
      <div class="score-badge ${scoreClass(op.score)}">${Math.round(op.score)}</div>
      <div class="oport-info">
        <div class="oport-nombre">
          ${l.nombre}
          ${urgente ? '<span class="tag-urgente">¡Cierra pronto!</span>' : ''}
        </div>
        <div class="oport-meta">${l.organismo || '—'} · ${l.region || 'Sin región'}</div>
      </div>
      <div class="oport-right">
        <div class="oport-monto">${fmt(l.monto_estimado)}</div>
        <div class="oport-cierre">Cierre: ${fmtFecha(l.fecha_cierre)}</div>
      </div>
    </div>`;
  }).join("");
}

/* Slider de score */
$("score-filter").addEventListener("input", e => {
  state.scoreMin = Number(e.target.value);
  $("score-val").textContent = state.scoreMin;
  loadOportunidades();
});

/* ─── LICITACIONES ──────────────────────────────────────────────── */
async function loadLicitaciones() {
  const tbody = $("tbody-licitaciones");
  tbody.innerHTML = '<tr><td colspan="7" class="loading">Cargando…</td></tr>';

  const offset = state.paginaLic * state.limitLic;
  let url = `/licitaciones?limit=${state.limitLic}&offset=${offset}`;
  if (state.organismoFiltro) url += `&organismo=${encodeURIComponent(state.organismoFiltro)}`;

  try {
    const data = await api(url);
    if (!data.licitaciones.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty">Sin resultados.</td></tr>';
      return;
    }
    tbody.innerHTML = data.licitaciones.map(l => `
      <tr onclick="abrirModalLic('${l.id}')">
        <td style="font-family:monospace;font-size:12px;color:var(--champagne)">${l.id}</td>
        <td style="max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${l.nombre}</td>
        <td style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-muted)">${l.organismo || '—'}</td>
        <td>${l.region || '—'}</td>
        <td>${fmt(l.monto_estimado)}</td>
        <td>${fmtFecha(l.fecha_cierre)}</td>
        <td><span class="badge-estado badge-${(l.estado||'').toLowerCase()}">${l.estado || '—'}</span></td>
      </tr>`).join("");

    $("pag-info").textContent = `Página ${state.paginaLic + 1} · ${data.total.toLocaleString("es-CL")} total`;
    $("btn-prev").disabled = state.paginaLic === 0;
    $("btn-next").disabled = offset + state.limitLic >= data.total;
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">${e.message}</td></tr>`;
  }
}

$("btn-prev").addEventListener("click", () => { state.paginaLic--; loadLicitaciones(); });
$("btn-next").addEventListener("click", () => { state.paginaLic++; loadLicitaciones(); });

let searchTimer;
$("search-organismo").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.organismoFiltro = e.target.value;
    state.paginaLic = 0;
    loadLicitaciones();
  }, 400);
});

/* ─── MODAL ─────────────────────────────────────────────────────── */
function abrirModal(op) {
  const l = op.licitacion;
  const d = op.score_detalle || {};
  const horas = horasRestantes(l.fecha_cierre);

  const barras = [
    { label: "Similitud semántica", max: 40, val: d.similaridad || 0 },
    { label: "Región",              max: 20, val: d.region || 0 },
    { label: "Rango de monto",      max: 20, val: d.monto || 0 },
    { label: "Urgencia",            max: 10, val: d.urgencia || 0 },
    { label: "Bono competencia",    max: 10, val: d.bono_competencia || 0 },
  ];

  $("modal-content").innerHTML = `
    <div class="modal-score-big">${Math.round(op.score)}</div>
    <div class="modal-score-label">Score de oportunidad / 100</div>
    <div class="modal-nombre">${l.nombre}</div>
    <div class="modal-organismo">${l.organismo || '—'} · ${l.region || 'Sin región'}</div>

    <div class="modal-grid">
      <div class="modal-field">
        <div class="modal-field-label">Monto estimado</div>
        <div class="modal-field-value">${fmt(l.monto_estimado)}</div>
      </div>
      <div class="modal-field">
        <div class="modal-field-label">Fecha de cierre</div>
        <div class="modal-field-value">${fmtFecha(l.fecha_cierre)}
          ${horas && horas > 0 && horas < 48 ? '<span class="tag-urgente">Urgente</span>' : ''}
        </div>
      </div>
      <div class="modal-field">
        <div class="modal-field-label">Estado</div>
        <div class="modal-field-value">${l.estado || '—'}</div>
      </div>
      <div class="modal-field">
        <div class="modal-field-label">Código</div>
        <div class="modal-field-value" style="font-family:monospace;font-size:12px">${l.id}</div>
      </div>
    </div>

    <div class="section-title" style="margin-bottom:12px">Desglose del score</div>
    ${barras.map(b => `
      <div class="score-bar-row">
        <div class="score-bar-label">
          <span>${b.label}</span>
          <span>${b.val.toFixed(0)} / ${b.max}</span>
        </div>
        <div class="score-bar-bg">
          <div class="score-bar-fill" style="width:${(b.val/b.max)*100}%"></div>
        </div>
      </div>`).join("")}

    <a class="btn-ver-mp"
       href="https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion=${l.id}"
       target="_blank">Ver en Mercado Público →</a>`;

  $("modal").classList.remove("hidden");
}

async function abrirModalLic(id) {
  try {
    const l = await api(`/licitaciones/${id}`);
    $("modal-content").innerHTML = `
      <div class="modal-nombre">${l.nombre}</div>
      <div class="modal-organismo">${l.organismo || '—'} · ${l.region || 'Sin región'}</div>
      <div class="modal-grid" style="margin-top:16px">
        <div class="modal-field">
          <div class="modal-field-label">Monto estimado</div>
          <div class="modal-field-value">${fmt(l.monto_estimado)}</div>
        </div>
        <div class="modal-field">
          <div class="modal-field-label">Cierre</div>
          <div class="modal-field-value">${fmtFecha(l.fecha_cierre)}</div>
        </div>
        <div class="modal-field">
          <div class="modal-field-label">Estado</div>
          <div class="modal-field-value">${l.estado}</div>
        </div>
        <div class="modal-field">
          <div class="modal-field-label">Código</div>
          <div class="modal-field-value" style="font-family:monospace;font-size:12px">${l.id}</div>
        </div>
      </div>
      ${l.descripcion ? `<div style="margin-top:16px;color:var(--text-muted);font-size:13px;line-height:1.6">${l.descripcion.slice(0,600)}${l.descripcion.length > 600 ? '…' : ''}</div>` : ''}
      <a class="btn-ver-mp"
         href="https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion=${l.id}"
         target="_blank">Ver en Mercado Público →</a>`;
    $("modal").classList.remove("hidden");
  } catch(e) { alert(e.message); }
}

$("modal-close").addEventListener("click", () => $("modal").classList.add("hidden"));
$("modal").addEventListener("click", e => { if (e.target === $("modal")) $("modal").classList.add("hidden"); });

/* ─── PERFIL ─────────────────────────────────────────────────────── */

// Generar checkboxes de regiones
const grid = $("check-regiones");
REGIONES.forEach(r => {
  const label = document.createElement("label");
  label.innerHTML = `<input type="checkbox" value="${r}" /> ${r}`;
  grid.appendChild(label);
});

$("btn-cargar-perfil").addEventListener("click", async () => {
  const rut = prompt("Ingresa tu RUT para cargar el perfil:");
  if (!rut) return;
  try {
    const p = await api(`/proveedores/${rut}`);
    $("f-rut").value    = p.rut;
    $("f-nombre").value = p.nombre;
    $("f-email").value  = p.email;
    $("f-rubros").value = p.rubros;
    $("f-monto-min").value = p.monto_min || "";
    $("f-monto-max").value = p.monto_max >= 999_999_999_999 ? "" : p.monto_max;

    grid.querySelectorAll("input[type=checkbox]").forEach(cb => {
      cb.checked = (p.regiones || []).includes(cb.value);
    });
    setRut(rut);
    showMsg("form-msg", "Perfil cargado correctamente.", "ok");
  } catch(e) {
    showMsg("form-msg", e.message, "error");
  }
});

$("form-perfil").addEventListener("submit", async e => {
  e.preventDefault();
  const regiones = [...grid.querySelectorAll("input:checked")].map(c => c.value);
  const body = {
    rut:       $("f-rut").value.trim(),
    nombre:    $("f-nombre").value.trim(),
    email:     $("f-email").value.trim(),
    rubros:    $("f-rubros").value.trim(),
    regiones,
    monto_min: Number($("f-monto-min").value) || 0,
    monto_max: Number($("f-monto-max").value) || 999_999_999_999,
  };

  try {
    // Intentar crear, si existe actualizar
    let p;
    try {
      p = await api("/proveedores", { method: "POST", body: JSON.stringify(body) });
    } catch(_) {
      p = await api(`/proveedores/${body.rut}`, { method: "PUT", body: JSON.stringify(body) });
    }
    setRut(p.rut);
    showMsg("form-msg", "Perfil guardado. El motor calculará tus oportunidades en segundos.", "ok");

    // Forzar recálculo
    await api("/ingesta/forzar", { method: "POST" });
  } catch(e) {
    showMsg("form-msg", e.message, "error");
  }
});

function showMsg(id, txt, type) {
  const el = $(id);
  el.textContent = txt;
  el.className = `form-msg ${type}`;
}

/* ─── Forzar ingesta ─────────────────────────────────────────────── */
$("btn-forzar-ingesta").addEventListener("click", async () => {
  $("btn-forzar-ingesta").textContent = "Actualizando…";
  $("btn-forzar-ingesta").disabled = true;
  try {
    await api("/ingesta/forzar", { method: "POST" });
    await loadDashboard();
  } finally {
    $("btn-forzar-ingesta").textContent = "↻ Actualizar ahora";
    $("btn-forzar-ingesta").disabled = false;
  }
});

/* ─── Init ──────────────────────────────────────────────────────── */
loadDashboard();
loadLicitaciones();
