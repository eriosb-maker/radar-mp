/* ─── Due Diligence — Lógica de UI ─────────────────────────────── */

const $ = id => document.getElementById(id);
const fmt = n => n != null && n > 0 ? `$ ${Math.round(n).toLocaleString("es-CL")} CLP` : "No informado";
const fmtFecha = iso => iso ? new Date(iso).toLocaleDateString("es-CL") : "—";
const varColor = v => v == null ? "" : v > 0 ? "color:#2ecc71" : "color:#e74c3c";

let informe_actual = null;
let rut_actual     = null;

/* ─── Pasos ─────────────────────────────────────────────────────── */
function setStep(n) {
  for (let i = 1; i <= 4; i++) {
    const el = $(`step-${i}`);
    el.classList.remove("active", "done");
    if (i < n)  el.classList.add("done");
    if (i === n) el.classList.add("active");
  }
}

function setLoader(msg) {
  $("loader-msg").textContent = msg;
  $("loader").style.display = "flex";
}

function hideLoader() {
  $("loader").style.display = "none";
}

/* ─── Tabs ──────────────────────────────────────────────────────── */
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    tab.classList.add("active");
    $(`tab-${tab.dataset.tab}`).classList.add("active");
  });
});

/* ─── Buscar ─────────────────────────────────────────────────────── */
async function buscar(rut) {
  $("error-msg").style.display = "none";
  $("result").classList.remove("visible");
  $("steps").style.display = "flex";
  setStep(1);
  setLoader("Identificando empresa en Mercado Público…");

  try {
    setStep(2); setLoader("Descargando historial de contratos…");
    await new Promise(r => setTimeout(r, 400));

    setStep(3); setLoader("Calculando métricas y detectando alertas…");
    await new Promise(r => setTimeout(r, 300));

    setStep(4); setLoader("Generando análisis con IA (Claude Opus)…");

    const resp = await fetch(`/api/dd/${encodeURIComponent(rut)}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Error desconocido");
    }

    informe_actual = await resp.json();
    rut_actual     = rut;

    hideLoader();
    setStep(5);   // todos ✓
    for (let i = 1; i <= 4; i++) $(`step-${i}`).classList.replace("active", "done");

    renderInforme(informe_actual);

  } catch(e) {
    hideLoader();
    $("steps").style.display = "none";
    $("error-msg").textContent = e.message;
    $("error-msg").style.display = "block";
  }
}

/* ─── Render ─────────────────────────────────────────────────────── */
function renderInforme(inf) {
  const m = inf.metricas;
  const p = inf.proveedor;

  // Header
  $("r-nombre").textContent = p.nombre || p.rut;
  $("r-rut").textContent    = `RUT: ${p.rut}  ·  Código MP: ${p.codigo || "—"}  ·  Período: ${fmtFecha(m.primer_contrato)} – ${fmtFecha(m.ultimo_contrato)}`;

  const nivel = inf.red_flags.some(f => f.nivel === "ALTO") ? "ALTO" :
                inf.red_flags.length > 0                    ? "MEDIO" : "BAJO";
  $("r-riesgo").textContent = `Riesgo ${nivel}`;
  $("r-riesgo").className   = `riesgo-badge riesgo-${nivel}`;

  // KPIs
  $("kpi-total").textContent     = fmt(m.total_adjudicado);
  $("kpi-contratos").textContent = `${m.total_contratos} (${m.total_con_monto} c/monto)`;
  $("kpi-promedio").textContent  = fmt(m.monto_promedio);
  $("kpi-organismos").textContent = m.organismos_unicos;
  $("kpi-flags").innerHTML = inf.red_flags.length > 0
    ? `<span style="color:${nivel==='ALTO'?'#e74c3c':'#e67e22'}">${inf.red_flags.length}</span>`
    : `<span style="color:#2ecc71">0</span>`;
  $("kpi-hhi").textContent = m.hhi.toFixed(4);

  // ── Tab Organismos ──────────────────────────────────────────────
  const top    = m.top_organismos || [];
  const barras = $("org-bars");
  barras.innerHTML = top.slice(0, 5).map(o => `
    <div class="bar-row">
      <div class="bar-label">
        <span>${o.nombre}</span>
        <span>${o.porcentaje}%  ·  ${fmt(o.monto)}</span>
      </div>
      <div class="bar-bg">
        <div class="bar-fill" style="width:${o.porcentaje}%"></div>
      </div>
    </div>`).join("");

  const tbodyOrg = document.querySelector("#tabla-organismos tbody");
  tbodyOrg.innerHTML = top.map(o => `
    <tr>
      <td>${o.nombre}</td>
      <td>${fmt(o.monto)}</td>
      <td>${o.contratos}</td>
      <td>${o.porcentaje}%</td>
    </tr>`).join("");

  // ── Tab Evolución ───────────────────────────────────────────────
  const porAnio  = m.por_anio || {};
  const varYoy   = m.variacion_yoy || {};
  const tbodyAnio = document.querySelector("#tabla-anio tbody");
  tbodyAnio.innerHTML = Object.entries(porAnio)
    .sort(([a], [b]) => a - b)
    .map(([anio, v]) => {
      const vari = varYoy[anio];
      const variTxt = vari != null
        ? `<span style="${varColor(vari)}">${vari > 0 ? "+" : ""}${vari}%</span>`
        : "—";
      return `
      <tr>
        <td>${anio}</td>
        <td>${fmt(v.monto)}</td>
        <td>${v.contratos}</td>
        <td>${variTxt}</td>
      </tr>`;
    }).join("");

  // ── Tab Flags ───────────────────────────────────────────────────
  const flagsList = $("flags-list");
  if (!inf.red_flags.length) {
    flagsList.innerHTML = '<div class="empty-state" style="padding:32px 0;color:var(--text-muted)">No se detectaron alertas de riesgo.</div>';
  } else {
    flagsList.innerHTML = inf.red_flags.map(f => `
      <div class="flag-card flag-${f.nivel}">
        <div class="flag-titulo">[${f.nivel}] ${f.titulo}</div>
        <div class="flag-detalle">${f.detalle}</div>
        <div class="flag-valor">Dato observado: ${f.valor || "—"}</div>
      </div>`).join("");
  }

  // ── Tab IA ──────────────────────────────────────────────────────
  const iaText = inf.analisis_ia || "Sin análisis disponible.";
  $("ia-text").innerHTML = iaText
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");

  // ── Tab Contratos ───────────────────────────────────────────────
  const contratos = m.contratos_detalle || [];
  const tbodyCont = document.querySelector("#tabla-contratos tbody");
  tbodyCont.innerHTML = contratos.map(c => `
    <tr>
      <td style="font-family:monospace;font-size:11px;color:var(--champagne)">${c.id || "—"}</td>
      <td style="max-width:240px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${c.nombre || "—"}</td>
      <td style="color:var(--text-muted)">${c.organismo || "—"}</td>
      <td>${fmt(c.monto)}</td>
      <td>${fmtFecha(c.fecha?.split("T")[0])}</td>
      <td><span style="font-size:10px;color:var(--text-muted)">${c.tipo === "licitacion" ? "Licitación" : "Orden de compra"}</span></td>
    </tr>`).join("");

  $("result").classList.add("visible");
}

/* ─── Descarga DOCX ─────────────────────────────────────────────── */
$("btn-docx").addEventListener("click", () => {
  if (!rut_actual) return;
  window.location.href = `/api/dd/${encodeURIComponent(rut_actual)}/docx`;
});

/* ─── Eventos ────────────────────────────────────────────────────── */
$("btn-buscar").addEventListener("click", () => {
  const rut = $("input-rut").value.trim();
  if (!rut) return;
  buscar(rut);
});

$("input-rut").addEventListener("keydown", e => {
  if (e.key === "Enter") $("btn-buscar").click();
});

// Formateo automático del RUT al escribir
$("input-rut").addEventListener("input", e => {
  let v = e.target.value.replace(/[^0-9kK\-\.]/g, "");
  e.target.value = v;
});
