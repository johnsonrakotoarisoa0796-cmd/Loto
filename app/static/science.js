(() => {
  const $ = (selector) => document.querySelector(selector);
  const fmt = (value, digits = 3) => value == null ? "—" : Number(value).toLocaleString("fr-FR", { maximumFractionDigits: digits });
  const pct = (value) => value == null ? "—" : `${fmt(value * 100, 2)} %`;
  const pText = (value) => value == null ? "—" : (value < 0.0001 ? "< 0,0001" : fmt(value, 4));
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[ch]);

  function toast(message, error = false) {
    const node = $("#science-toast");
    node.textContent = message;
    node.classList.toggle("error", error);
    node.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove("show"), 3500);
  }

  function signalLabel(p) {
    if (p == null) return `<span class="science-state neutral">NON TESTÉ</span>`;
    if (p < 0.01) return `<span class="science-state alert">À RÉPLIQUER</span>`;
    if (p < 0.05) return `<span class="science-state watch">À SURVEILLER</span>`;
    return `<span class="science-state neutral">NON SIGNIFICATIF</span>`;
  }

  function render(data) {
    const { meta, status, theory, number_tests, pair_tests, lag_tests, model_validation } = data;
    $("#science-draw-count").textContent = fmt(meta.draw_count, 0);
    $("#science-date-range").textContent = meta.first_date && meta.last_date ? `${meta.first_date} → ${meta.last_date}` : "Aucune donnée";
    $("#science-test-count").textContent = fmt(meta.family_tests, 0);
    $("#science-signal-count").textContent = fmt(status.number_signals + status.pair_signals + status.lag_signals, 0);
    $("#science-edge").textContent = status.candidate_predictive_signal ? "CANDIDAT" : "NON";
    $("#science-edge-note").textContent = status.candidate_predictive_signal ? "50 nouveaux tirages requis pour confirmer" : "Aucun avantage robuste démontré";
    const statusBox = $("#science-status");
    statusBox.className = `science-status status-${status.level}`;
    $("#science-status-title").textContent = status.headline;
    $("#science-status-text").textContent = status.explanation;
    $("#science-status-badge").textContent = status.level === "insufficient" ? "ÉCHANTILLON COURT" : status.level === "candidate" ? "SIGNAL À RÉPLIQUER" : "SURVEILLANCE ACTIVE";

    $("#science-number-rows").innerHTML = number_tests.map(row => `
      <tr><td><b class="science-number">${String(row.number).padStart(2,"0")}</b></td><td>${fmt(row.count,0)}</td><td>${fmt(row.expected_count,2)}</td><td class="${row.difference >= 0 ? "positive" : "negative"}">${row.difference >= 0 ? "+" : ""}${fmt(row.difference,2)}</td><td>${pText(row.p_value)}</td><td><b>${pText(row.p_adjusted)}</b></td><td>${signalLabel(row.p_adjusted)}</td></tr>`).join("");

    $("#science-pair-rows").innerHTML = pair_tests.map(row => `
      <tr><td><div class="science-pair"><b>${String(row.numbers[0]).padStart(2,"0")}</b><i>+</i><b>${String(row.numbers[1]).padStart(2,"0")}</b></div></td><td>${fmt(row.count,0)}</td><td>${fmt(row.expected_count,2)}</td><td>${pText(row.p_value)}</td><td><b>${pText(row.p_adjusted)}</b></td><td>${signalLabel(row.p_adjusted)}</td></tr>`).join("") || `<tr><td colspan="6" class="science-empty">Pas encore assez de données.</td></tr>`;

    $("#science-lag-rows").innerHTML = lag_tests.map(row => `
      <div class="science-lag-row"><div><strong>Retard ${row.lag}</strong><small>${row.independent_pairs} paires indépendantes · p ${pText(row.p_adjusted)}</small></div><div class="science-lag-value"><b>${fmt(row.mean_shared,2)}</b><small>attendu ${fmt(row.expected_mean_shared,3)}</small></div>${signalLabel(row.p_adjusted)}</div>`).join("");

    if (!model_validation.available) {
      $("#science-model-validation").innerHTML = `<div class="model-wait"><b>Validation non concluante pour le moment</b><p>${esc(model_validation.reason)}</p><div class="model-mini-stats"><span>Apprentissage requis <b>${fmt(model_validation.training_draws,0)} / ${MIN_TRAINING()}</b></span><span>Test hors échantillon <b>${fmt(model_validation.holdout_draws,0)} / ${fmt(model_validation.minimum_holdout_required,0)}</b></span></div></div>`;
    } else {
      const overall = model_validation.overall;
      $("#science-model-validation").innerHTML = `
        <div class="model-result"><span>MOYENNE MODÈLE / 5</span><strong>${fmt(overall.mean_hits,3)}</strong><small>Référence aléatoire : ${fmt(overall.expected_hits,3)}</small></div>
        <div class="model-result"><span>TEST GLOBAL</span><strong>${pText(overall.p_value_upper)}</strong><small>p-value unilatérale · ${esc(overall.p_value_method)}</small></div>
        <div class="model-periods"><div><b>Période 1</b><span>${model_validation.first_period.total_hits}/${model_validation.first_period.forecasts * 5} numéros touchés</span><small>p ajusté = ${pText(model_validation.first_period.p_value_adjusted_global)}</small></div><div><b>Période de confirmation</b><span>${model_validation.confirmation_period.total_hits}/${model_validation.confirmation_period.forecasts * 5} numéros touchés</span><small>p ajusté = ${pText(model_validation.confirmation_period.p_value_adjusted_global)}</small></div></div>
        <p class="model-verdict">${esc(model_validation.reason)}</p>`;
    }
  }

  function MIN_TRAINING() { return 60; }

  async function loadAudit() {
    const button = $("#science-refresh");
    button.disabled = true;
    button.textContent = "Calcul en cours…";
    try {
      const response = await fetch("/api/science", { credentials: "same-origin", cache: "no-store" });
      if (response.status === 401) { window.location.href = "/login"; return; }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Erreur ${response.status}`);
      render(payload);
      toast("Audit scientifique actualisé.");
    } catch (error) {
      toast(error.message || "Impossible de charger l'audit.", true);
    } finally {
      button.disabled = false;
      button.textContent = "↻ Relancer l'audit";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#science-refresh").addEventListener("click", loadAudit);
    loadAudit();
  });
})();
