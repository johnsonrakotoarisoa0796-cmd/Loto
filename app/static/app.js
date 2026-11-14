(() => {
  const state = { draws: [], analysis: null, forecastHistory: [], csrf: window.LOTO_CSRF || "", editingId: null };
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const numberFmt = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

  function formatDate(value, options = { day: "2-digit", month: "short", year: "numeric" }) {
    if (!value) return "—";
    const date = new Date(`${value}T12:00:00`);
    return new Intl.DateTimeFormat("fr-FR", options).format(date).replace(".", "");
  }
  function pct(value, digits = 1) {
    return value == null ? "—" : `${(value * 100).toLocaleString("fr-FR", { maximumFractionDigits: digits })} %`;
  }
  function ball(n, shared = false, small = false) {
    return `<span class="ball${shared ? " shared" : ""}${small ? " small" : ""}">${String(n).padStart(2, "0")}</span>`;
  }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  }
  function toast(message, isError = false) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.toggle("error", isError);
    node.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove("show"), 3400);
  }
  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.csrf && !["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) {
      headers.set("X-CSRF-Token", state.csrf);
    }
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      if (response.status === 401) window.location.href = "/login";
      throw new Error(payload?.detail || `Erreur ${response.status}`);
    }
    return payload;
  }

  function switchView(view) {
    const allowed = ["overview", "history", "analysis", "prediction"];
    if (!allowed.includes(view)) return;
    $$(".page").forEach((page) => page.classList.toggle("active", page.id === `view-${view}`));
    $$(".nav-item").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const labels = { overview: "Vue d'ensemble", history: "Historique", analysis: "Analyses statistiques", prediction: "Laboratoire de scores" };
    $("#page-crumb").textContent = labels[view];
    history.replaceState(null, "", `#${view}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderOverview() {
    const { summary, frequencies, transitions } = state.analysis;
    $("#kpi-draws").textContent = numberFmt.format(summary.draw_count);
    $("#kpi-latest").textContent = summary.latest_date ? formatDate(summary.latest_date, { day: "2-digit", month: "short" }) : "—";
    $("#kpi-repeat").textContent = summary.daily_transition_count ? pct(summary.daily_repeat_rate) : "—";
    $("#kpi-repeat-foot").textContent = summary.daily_transition_count
      ? `${summary.daily_repeat_count}/${summary.daily_transition_count} transitions · Théorie : 56,1 %`
      : "Enregistre deux jours consécutifs pour comparer";
    $("#kpi-unique").innerHTML = `${summary.unique_numbers_seen}<small>/35</small>`;
    $("#nav-draw-count").textContent = summary.draw_count;
    $("#today-label").textContent = summary.latest_date ? `DERNIÈRE MISE À JOUR · ${formatDate(summary.latest_date).toUpperCase()}` : "HISTORIQUE 5/35";

    const top = [...frequencies].sort((a, b) => b.count - a.count || a.number - b.number).slice(0, 10);
    const max = Math.max(1, ...top.map((r) => r.count));
    $("#top-frequency").innerHTML = top.length ? top.map((row) => `
      <div class="bar-row"><span class="bar-number">${String(row.number).padStart(2, "0")}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, row.count / max * 100)}%"></div></div>
      <span class="bar-count">${row.count}</span></div>`).join("") : `<div class="empty-state">Ajoute un premier tirage pour voir les fréquences.</div>`;
    $("#frequency-baseline").textContent = summary.draw_count ? `Moyenne attendue : ${summary.draw_count / 7 < 10 ? numberFmt.format(summary.draw_count / 7) : numberFmt.format(summary.draw_count / 7)} par numéro` : "Moyenne attendue : —";

    $("#recent-draws").innerHTML = state.draws.slice(0, 5).map((draw) => `
      <div class="recent-row"><span class="recent-date">${formatDate(draw.date, { day: "2-digit", month: "short" })}</span>
      <div class="ball-row">${draw.numbers.map((n) => ball(n, false, true)).join("")}</div></div>`).join("") || `<div class="empty-state">Aucun tirage enregistré.</div>`;

    $("#repeat-count").textContent = summary.daily_transition_count ? `${summary.daily_repeat_count}/${summary.daily_transition_count}` : "—";
    $("#repeat-observed-label").textContent = `Observé : ${summary.daily_transition_count ? pct(summary.daily_repeat_rate) : "—"}`;
    $("#repeat-progress-fill").style.width = `${Math.min(100, (summary.daily_repeat_rate || 0) * 100)}%`;
    const daily = transitions.filter((t) => t.is_next_calendar_day).slice(0, 7).reverse();
    $("#repeat-timeline").innerHTML = daily.length ? daily.map((t) => `
      <div class="timeline-item ${t.shared_count ? "has-repeat" : ""}"><span class="timeline-date">${formatDate(t.to_date, { day: "2-digit", month: "short" })}</span>
      <strong>${t.shared_count ? t.shared_numbers.map((n) => String(n).padStart(2, "0")).join(" · ") : "Aucun"}</strong><small>${t.shared_count} commun${t.shared_count > 1 ? "s" : ""}</small></div>`).join("") : `<div class="empty-state">Pas encore assez de jours consécutifs.</div>`;
    const pValue = summary.daily_repeat_binomial_tail;
    $("#repeat-statistical-test").textContent = pValue == null
      ? "Le test statistique sera calculé dès qu'il y aura au moins une paire de dates consécutives."
      : `Test binomial unilatéral : p = ${pValue.toLocaleString("fr-FR", { maximumFractionDigits: 3 })}. C'est la probabilité d'observer au moins autant de répétitions si la référence théorique de 56,1 % est correcte.`;
  }

  function renderHistory() {
    const query = $("#history-search").value.trim().toLowerCase();
    const filtered = state.draws.filter((d) => {
      const haystack = `${d.date} ${d.numbers.join(" ")} ${d.source} ${d.notes || ""}`.toLowerCase();
      return haystack.includes(query);
    });
    $("#history-total").textContent = `${state.draws.length} tirage${state.draws.length > 1 ? "s" : ""}`;
    $("#history-showing").textContent = `${filtered.length} résultat${filtered.length > 1 ? "s" : ""} affiché${filtered.length > 1 ? "s" : ""}`;
    $("#history-body").innerHTML = filtered.length ? filtered.map((draw) => `
      <tr><td>${formatDate(draw.date)}</td><td><div class="ball-row">${draw.numbers.map((n) => ball(n, false, true)).join("")}</div></td>
      <td>${escapeHtml(draw.source || "Saisie manuelle")}</td><td>${escapeHtml(draw.notes || "—")}</td>
      <td class="align-right"><button class="table-action" data-edit="${draw.id}" title="Modifier">✎</button><button class="table-action delete" data-delete="${draw.id}" title="Supprimer">×</button></td></tr>`).join("") : `<tr><td colspan="5" class="empty-cell">Aucun tirage ne correspond à ta recherche.</td></tr>`;
    $$("[data-edit]").forEach((button) => button.addEventListener("click", () => openEdit(Number(button.dataset.edit))));
    $$("[data-delete]").forEach((button) => button.addEventListener("click", () => deleteDraw(Number(button.dataset.delete))));
  }

  function renderAnalysis() {
    const { summary, frequencies, reappearance, frequent_pairs, overlap_histogram, transitions } = state.analysis;
    $("#analysis-sample").textContent = `ÉCHANTILLON : ${summary.draw_count} TIRAGES`;
    const expected = summary.draw_count / 7;
    const sd = Math.sqrt(summary.draw_count * (1 / 7) * (6 / 7)) || 1;
    $("#all-frequency").innerHTML = frequencies.map((row) => {
      const z = (row.count - expected) / sd;
      const level = z > .65 ? "high" : z < -.65 ? "low" : "mid";
      return `<div class="heat-cell ${level}" title="${row.count} sortie(s), moyenne attendue ${numberFmt.format(expected)}, écart actuel ${row.gap === null ? "jamais sorti" : `${row.gap} tirage(s)`}"><strong>${String(row.number).padStart(2, "0")}</strong><span>${row.count}× · Δ${row.gap === null ? "—" : row.gap}</span></div>`;
    }).join("");
    const reappTop = reappearance.filter((x) => x.opportunities > 0).slice(0, 8);
    $("#reappearance-list").innerHTML = reappTop.length ? reappTop.map((row) => `
      <div class="compact-row"><strong>${String(row.number).padStart(2, "0")}</strong><span>${row.returned_next_record}/${row.opportunities} retours observés</span><b>${pct(row.rate, 0)}</b></div>`).join("") : `<div class="empty-state">Ajoute plus de tirages pour calculer les retours.</div>`;
    $("#pairs-list").innerHTML = frequent_pairs.length ? frequent_pairs.slice(0, 8).map((pair) => `
      <div class="pair-row"><div class="pair-left">${pair.numbers.map((n) => ball(n, false, true)).join("")}</div><span>${pair.count} fois</span></div>`).join("") : `<div class="empty-state">Pas encore de paires.</div>`;
    const maxOverlap = Math.max(1, ...overlap_histogram.map((x) => x.count));
    $("#overlap-chart").innerHTML = overlap_histogram.map((row) => `
      <div class="overlap-row"><span>${row.shared} commun${row.shared > 1 ? "s" : ""}</span><div class="overlap-track"><i style="width:${row.count / maxOverlap * 100}%"></i></div><strong>${row.count}</strong></div>`).join("");
    $("#transition-body").innerHTML = transitions.length ? transitions.map((t) => `
      <tr><td>${formatDate(t.from_date)}</td><td>${formatDate(t.to_date)}</td><td>${t.shared_count ? `<div class="ball-row">${t.shared_numbers.map((n) => ball(n, true, true)).join("")}</div>` : `<span class="no-repeat">Aucun numéro commun</span>`}</td><td>${t.calendar_days_apart} jour${t.calendar_days_apart > 1 ? "s" : ""}</td></tr>`).join("") : `<tr><td colspan="4" class="empty-cell">Deux tirages sont nécessaires.</td></tr>`;
  }

  function renderPrediction() {
    const { prediction, backtest } = state.analysis;
    $("#prediction-combo").innerHTML = prediction.numbers.map((n) => `<span>${String(n).padStart(2, "0")}</span>`).join("　·　");
    const top = prediction.ranked.slice(0, 15);
    const min = Math.min(...top.map((x) => x.score));
    const max = Math.max(...top.map((x) => x.score));
    $("#prediction-ranking").innerHTML = top.map((row, index) => {
      const width = max === min ? 50 : 16 + (row.score - min) / (max - min) * 84;
      return `<div class="ranking-row"><span class="rank-index">${String(index + 1).padStart(2, "0")}</span><span class="bar-number">${String(row.number).padStart(2, "0")}</span><div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div><span class="score">${pct(row.score, 2)}</span></div>`;
    }).join("");
    $("#alternative-combos").innerHTML = prediction.alternatives.map((combo, index) => `
      <div class="alternative-row"><span>SCÉNARIO ${index + 2}</span><div class="ball-row">${combo.map((n) => ball(n)).join("")}</div></div>`).join("");
    if (!backtest.available) {
      $("#backtest-content").innerHTML = `<div class="backtest-message">${escapeHtml(backtest.reason)}<br>Le test sera activé automatiquement quand l'historique sera assez long.</div>`;
    } else {
      const advantage = backtest.model_average_hits - backtest.random_expected_hits;
      $("#backtest-content").innerHTML = `
        <div class="backtest-metric"><span>Tirages testés</span><strong>${backtest.tested_draws}</strong></div>
        <div class="backtest-metric"><span>Moyenne du modèle</span><strong>${backtest.model_average_hits.toFixed(2).replace(".", ",")} / 5</strong></div>
        <div class="backtest-metric"><span>Référence aléatoire</span><strong>${backtest.random_expected_hits.toFixed(2).replace(".", ",")} / 5</strong></div>
        <div class="backtest-message">Écart observé : ${advantage >= 0 ? "+" : ""}${advantage.toFixed(2).replace(".", ",")} numéro(s) par tirage. ${escapeHtml(backtest.warning || "")} Ce résultat historique n'est pas une garantie de performance future.</div>`;
    }

    const forecasts = state.forecastHistory;
    $("#forecast-count").textContent = `${forecasts.length} ENREGISTRÉE${forecasts.length > 1 ? "S" : ""}`;
    $("#forecast-history-body").innerHTML = forecasts.length ? forecasts.map((item) => `
      <tr><td>${formatDate(item.based_on_latest_date)}<br><small>${item.based_on_draw_count} tirages disponibles</small></td>
      <td><div class="ball-row">${item.numbers.map((n) => ball(n, false, true)).join("")}</div></td>
      <td>${item.actual_draw_date ? formatDate(item.actual_draw_date) : `<span class="no-repeat">En attente du prochain tirage</span>`}</td>
      <td>${item.actual_numbers ? `<div class="ball-row">${item.actual_numbers.map((n) => ball(n, item.numbers.includes(n), true)).join("")}</div>` : "—"}</td>
      <td>${item.evaluated ? `<strong>${item.hits}/5</strong>` : "—"}</td></tr>`).join("") : `<tr><td colspan="5" class="empty-cell">Enregistre ton premier pronostic pour commencer à mesurer le modèle.</td></tr>`;
  }

  function renderAll() {
    renderOverview();
    renderHistory();
    renderAnalysis();
    renderPrediction();
  }

  async function loadData(showMessage = false) {
    try {
      const config = await api("/api/config");
      state.csrf = config.csrf_token;
      const [drawData, analysis, forecastData] = await Promise.all([api("/api/draws"), api("/api/analysis"), api("/api/prediction-history")]);
      state.draws = drawData.draws;
      state.analysis = analysis;
      state.forecastHistory = forecastData.predictions;
      renderAll();
      if (showMessage) toast("Données actualisées.");
    } catch (error) {
      toast(error.message, true);
    }
  }

  function openNew() {
    state.editingId = null;
    $("#draw-form").reset();
    $("#draw-id").value = "";
    $("#draw-dialog-title").textContent = "Ajouter un tirage";
    $("#save-draw").textContent = "Enregistrer le tirage";
    $("#draw-error").textContent = "";
    const today = new Date();
    $("#draw-date").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    $("#draw-source").value = "Saisie manuelle";
    $("#draw-dialog").showModal();
  }
  function openEdit(id) {
    const draw = state.draws.find((d) => d.id === id);
    if (!draw) return;
    state.editingId = id;
    $("#draw-id").value = id;
    $("#draw-dialog-title").textContent = "Modifier le tirage";
    $("#save-draw").textContent = "Enregistrer les modifications";
    $("#draw-date").value = draw.date;
    draw.numbers.forEach((n, i) => { $(`#num-${i + 1}`).value = n; });
    $("#draw-source").value = draw.source || "Saisie manuelle";
    $("#draw-notes").value = draw.notes || "";
    $("#draw-error").textContent = "";
    $("#draw-dialog").showModal();
  }
  async function saveDraw(event) {
    event.preventDefault();
    const numbers = [1, 2, 3, 4, 5].map((i) => Number($(`#num-${i}`).value));
    const date = $("#draw-date").value;
    if (!date || numbers.some((n) => !Number.isInteger(n) || n < 1 || n > 35) || new Set(numbers).size !== 5) {
      $("#draw-error").textContent = "Saisis une date et cinq numéros distincts entre 1 et 35.";
      return;
    }
    const payload = { date, numbers, source: $("#draw-source").value || "Saisie manuelle", notes: $("#draw-notes").value || null };
    const button = $("#save-draw");
    button.disabled = true;
    button.textContent = "Enregistrement…";
    try {
      const path = state.editingId ? `/api/draws/${state.editingId}` : "/api/draws";
      await api(path, { method: state.editingId ? "PUT" : "POST", body: JSON.stringify(payload) });
      $("#draw-dialog").close();
      toast(state.editingId ? "Tirage modifié." : "Nouveau tirage enregistré.");
      await loadData();
    } catch (error) {
      $("#draw-error").textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = state.editingId ? "Enregistrer les modifications" : "Enregistrer le tirage";
    }
  }
  async function deleteDraw(id) {
    const draw = state.draws.find((d) => d.id === id);
    if (!draw || !window.confirm(`Supprimer le tirage du ${formatDate(draw.date)} ? Cette action est définitive.`)) return;
    try {
      await api(`/api/draws/${id}`, { method: "DELETE" });
      toast("Tirage supprimé.");
      await loadData();
    } catch (error) { toast(error.message, true); }
  }

  async function importFile(file) {
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const result = await api("/api/import", { method: "POST", body: formData });
      toast(`${result.inserted} ajouté(s), ${result.ignored_duplicates} doublon(s) ignoré(s).`);
      await loadData();
    } catch (error) { toast(error.message, true); }
    $("#csv-file").value = "";
  }

  async function recordPrediction() {
    const button = $("#save-prediction");
    button.disabled = true;
    button.textContent = "Enregistrement…";
    try {
      const result = await api("/api/predictions/record", { method: "POST" });
      toast(result.already_recorded ? "Cette prévision est déjà enregistrée." : "Prévision enregistrée. Le résultat sera évalué au prochain tirage.");
      await loadData();
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "＋ Enregistrer ce pronostic";
    }
  }

  function bindEvents() {
    $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
    $$('[data-go]').forEach((button) => button.addEventListener("click", () => switchView(button.dataset.go)));
    $("#open-add").addEventListener("click", openNew);
    $("#history-add").addEventListener("click", openNew);
    $("#close-draw").addEventListener("click", () => $("#draw-dialog").close());
    $("#cancel-draw").addEventListener("click", () => $("#draw-dialog").close());
    $("#draw-form").addEventListener("submit", saveDraw);
    $("#history-search").addEventListener("input", renderHistory);
    $("#import-trigger").addEventListener("click", () => $("#csv-file").click());
    $("#csv-file").addEventListener("change", (event) => importFile(event.target.files[0]));
    $("#save-prediction").addEventListener("click", recordPrediction);
    if ($("#logout-button")) {
      $("#logout-button").addEventListener("click", async () => {
        try { await api("/logout", { method: "POST" }); window.location.href = "/login"; }
        catch (error) { toast(error.message, true); }
      });
    }
    const initialView = location.hash.slice(1);
    if (["overview", "history", "analysis", "prediction"].includes(initialView)) switchView(initialView);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadData();
  });
})();
