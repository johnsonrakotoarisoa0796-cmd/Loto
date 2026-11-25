(() => {
  const state = { draws: [], analysis: null, basePrediction: null, forecastHistory: [], contextualStudy: null, contextualLoading: false, contextualPrediction: null, contextualPredictionLoading: false, csrf: window.LOTO_CSRF || "", editingId: null };
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
    const response = await fetch(path, { ...options, headers, credentials: "same-origin", cache: "no-store" });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      if (response.status === 401) window.location.href = "/login";
      throw new Error(payload?.detail || `Erreur ${response.status}`);
    }
    return payload;
  }

  function switchView(view) {
    const allowed = ["overview", "history", "analysis", "prediction", "environment"];
    if (!allowed.includes(view)) return;
    $$(".page").forEach((page) => page.classList.toggle("active", page.id === `view-${view}`));
    $$(".nav-item").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const labels = { overview: "Vue d'ensemble", history: "Historique", analysis: "Analyses statistiques", prediction: "Laboratoire de scores", environment: "Climat & cosmos" };
    $("#page-crumb").textContent = labels[view];
    history.replaceState(null, "", `#${view}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (view === "environment" && !state.contextualStudy && !state.contextualLoading) loadContextualStudy();
    if (view === "prediction" && !state.contextualPrediction && !state.contextualPredictionLoading) loadContextualPrediction();
  }

  function renderOverview() {
    const { summary, frequencies, transitions } = state.analysis;
    $("#kpi-draws").textContent = numberFmt.format(summary.draw_count);
    $("#kpi-latest").textContent = summary.latest_date ? formatDate(summary.latest_date, { day: "2-digit", month: "short" }) : "—";
    $("#kpi-repeat").textContent = summary.successive_transition_count ? pct(summary.successive_repeat_rate) : "—";
    $("#kpi-repeat-foot").textContent = summary.successive_transition_count
      ? `${summary.successive_repeat_count}/${summary.successive_transition_count} paires de tirages · Théorie : 56,1 %`
      : "Enregistre au moins deux tirages pour comparer";
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


  function scoreIndex(value) {
    return value == null ? "—" : Number(value).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " pts";
  }

  function renderMovementList(rows, selector, direction, available) {
    const node = $(selector);
    if (!available) {
      node.innerHTML = '<div class="empty-state">Il faut au moins deux tirages pour comparer les rangs.</div>';
      return;
    }
    if (!rows.length) {
      node.innerHTML = '<div class="empty-state">Aucun mouvement de rang dans ce sens après le dernier tirage.</div>';
      return;
    }
    const arrow = direction === "up" ? "↗" : "↘";
    node.innerHTML = rows.map((row) =>
      '<div class="movement-row movement-' + direction + '">' +
        '<span class="movement-ball">' + String(row.number).padStart(2, "0") + '</span>' +
        '<span class="movement-ranks">#' + row.previous_rank + ' <i>→</i> #' + row.rank + '</span>' +
        '<strong>' + arrow + ' ' + Math.abs(row.rank_change) + ' place' + (Math.abs(row.rank_change) > 1 ? 's' : '') + '</strong>' +
      '</div>'
    ).join("");
  }

  function renderPrediction() {
    const { summary, prediction, backtest } = state.analysis;
    const models = prediction.models || [];
    const primary = models.find((model) => model.id === prediction.active_model_id) || models.find((model) => model.id === "hybrid") || models[0];
    const contextual = prediction.contextual_model || state.contextualPrediction;
    const contextNote = $("#prediction-context-note");
    if (contextNote) {
      if (!contextual) {
        contextNote.textContent = state.contextualPredictionLoading
          ? "Chargement des prévisions Open-Meteo et des observations astronomiques/sismiques…"
          : "Le modèle contextuel se charge à l'ouverture de ce laboratoire.";
      } else if (contextual.ready) {
        const features = (contextual.features_used_labels || []).join(", ");
        const forecastTime = contextual.forecast_weather && contextual.forecast_weather.weather_forecast_time_local;
        contextNote.textContent = "Modèle contextuel actif pour le " + formatDate(contextual.next_draw_date) +
          " à " + (contextual.reference_time_local || "16:35") + " (" + (contextual.timezone || "heure locale") + "). " +
          "Poids contextuel : " + Math.round((contextual.contextual_weight || 0) * 100) + " % ; " +
          (contextual.historical_context_draws || 0) + " contextes historiques utilisables. " +
          "Variables : " + (features || "météo et astronomie") +
          (forecastTime ? ". Prévision météo : " + forecastTime + "." : ".") +
          (contextual.seismic_snapshot && contextual.seismic_snapshot.snapshot_time_utc
            ? " Snapshot sismique du " + new Date(contextual.seismic_snapshot.snapshot_time_utc).toLocaleString("fr-FR") + "." : "") +
          " Actualise le modèle avant le tirage pour intégrer les prévisions et observations les plus récentes." +
          (contextual.location_is_estimate ? " Lieu géographique approximatif." : "");
      } else {
        contextNote.textContent = "Le modèle météo/cosmos n'est pas encore activé : " +
          (contextual.reason || "données contextuelles insuffisantes") +
          " Le classement affiché reste celui de l'historique et de la récence, sans inventer de signal.";
      }
    }
    $("#prediction-combo").innerHTML = prediction.numbers.map((n) => '<span>' + String(n).padStart(2, "0") + '</span>').join("　·　");
    if (primary) {
      $("#prediction-method-name").textContent = primary.label;
      $("#prediction-combo-score").textContent = "Indice moyen de la combinaison : " + scoreIndex(primary.score_index);
    }

    const top = prediction.ranked.slice(0, 15);
    const trendWindow = prediction.ranked[0]?.trend_window || 0;
    const latestDate = summary.latest_date ? formatDate(summary.latest_date) : "aucun tirage";
    let trendLabel = "tendance disponible à partir de 3 tirages";
    if (summary.draw_count >= 20) trendLabel = trendWindow + " derniers vs " + trendWindow + " précédents";
    else if (summary.draw_count >= 10) trendLabel = trendWindow + " derniers vs " + trendWindow + " précédents · signal provisoire";
    else if (summary.draw_count >= 3) trendLabel = "historique court · direction disponible après 10 tirages";
    $("#ranking-status").textContent = "Recalcul automatique · " + summary.draw_count + " tirage(s) · dernier résultat : " + latestDate + " · " + trendLabel;
    const min = Math.min(...top.map((x) => x.score_index));
    const max = Math.max(...top.map((x) => x.score_index));
    $("#prediction-ranking").innerHTML = top.map((row, index) => {
      const width = max === min ? 50 : 16 + (row.score_index - min) / (max - min) * 84;
      const movement = row.rank_change == null
        ? "premier classement"
        : row.rank_change > 0 ? "↗ +" + row.rank_change + " place" + (row.rank_change > 1 ? "s" : "")
        : row.rank_change < 0 ? "↘ " + row.rank_change + " place" + (row.rank_change < -1 ? "s" : "")
        : "→ stable";
      const trend = row.trend_direction === "up" ? "↗" : row.trend_direction === "down" ? "↘" : row.trend_direction === "stable" ? "→" : "·";
      return '<div class="ranking-row">' +
        '<span class="rank-index">' + String(index + 1).padStart(2, "0") + '</span>' +
        '<span class="bar-number">' + String(row.number).padStart(2, "0") + '</span>' +
        '<div class="bar-track"><div class="bar-fill" style="width:' + width + '%"></div></div>' +
        '<span class="score" title="Indice relatif base 100, pas une probabilité">' + scoreIndex(row.score_index) + '</span>' +
        '<span class="trend-value trend-' + row.trend_direction + '" title="' + escapeHtml(row.trend_basis || "") + '">' + trend + ' ' + movement + '</span>' +
      '</div>';
    }).join("");

    const alternatives = models.filter((model) => model.id !== (primary && primary.id));
    const methodCards = alternatives.map((model) =>
      '<section class="method-card">' +
        '<div class="method-card-head"><div><strong>' + escapeHtml(model.label) + '</strong><p>' + escapeHtml(model.description) + '</p></div>' +
        '<span class="method-index">' + scoreIndex(model.score_index) + '</span></div>' +
        '<div class="method-combo">' + model.numbers.map((n) => ball(n, false, true)).join("") + '</div>' +
        '<small>Indice moyen des 5 numéros · base 100</small>' +
      '</section>'
    ).join("");
    const diverseScenarios = prediction.diverse_scenarios || [];
    const diverseCards = diverseScenarios.map((scenario) =>
      '<section class="method-card diverse-scenario-card">' +
        '<div class="method-card-head"><div><strong>' + escapeHtml(scenario.label) + '</strong><p>' + escapeHtml(scenario.description) + '</p></div>' +
        '<span class="method-index">Diversité</span></div>' +
        '<div class="method-combo">' + scenario.numbers.map((n) => ball(n, false, true)).join("") + '</div>' +
        '<small>Communs avec la principale : ' + scenario.overlap_with_primary + '/5 · Rang moyen dans les 22 candidats : ' + scenario.mean_rank_in_pool + '</small>' +
      '</section>'
    ).join("");
    $("#alternative-combos").innerHTML = methodCards + diverseCards || '<div class="empty-state">Les scénarios seront affichés après le chargement des données.</div>';

    const movements = prediction.movements || { available: false, up: [], down: [] };
    renderMovementList(movements.up || [], "#rank-up-movers", "up", movements.available);
    renderMovementList(movements.down || [], "#rank-down-movers", "down", movements.available);

    const comparison = backtest.methods_comparison;
    if (!comparison || !comparison.available) {
      $("#backtest-content").innerHTML = '<div class="backtest-message">' + escapeHtml((comparison && comparison.reason) || backtest.reason || "Le comparatif chronologique est indisponible.") + '</div>';
    } else {
      const formatPValue = (value) => {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) return "—";
        return parsed < 0.001 ? "&lt; 0,001" : parsed.toLocaleString("fr-FR", { maximumFractionDigits: 3 });
      };
      const methodRows = comparison.methods.map((model) => {
        const difference = model.difference;
        const direction = difference > 0.000001 ? "positive" : difference < -0.000001 ? "negative" : "neutral";
        const signed = (difference > 0 ? "+" : "") + difference.toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
        const adjustedP = formatPValue(model.p_value_adjusted_holm);
        const confirmation = model.confirmed_candidate ? "Candidat statistique" :
          comparison.confirmation_ready ? "Non confirmé" : "À confirmer";
        return '<tr>' +
          '<td><strong>' + escapeHtml(model.label) + '</strong><small>' + escapeHtml(model.note) + '</small></td>' +
          '<td>' + model.tested_draws + '</td>' +
          '<td><strong>' + model.average_hits.toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' / 5</strong><small>' + (model.total_hits ?? "—") + ' touches cumulées</small></td>' +
          '<td>' + model.expected_hits.toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' / 5</td>' +
          '<td class="backtest-' + direction + '">' + signed + '</td>' +
          '<td>' + adjustedP + '</td>' +
          '<td>' + confirmation + '</td>' +
        '</tr>';
      }).join("");
      const caveat = comparison.tested_draws < 20
        ? "Échantillon très court : lecture descriptive uniquement."
        : comparison.tested_draws < 80
          ? "Il faut au moins 80 prévisions hors échantillon pour vérifier deux périodes de confirmation de 40."
          : comparison.candidate_edge
            ? "Un candidat statistique satisfait les seuils de confirmation ; il doit encore être surveillé prospectivement."
            : "Aucun modèle ne satisfait les critères de confirmation dans les deux périodes.";
      const contextualBacktest = contextual && contextual.backtest;
      const contextualDetail = contextualBacktest && contextualBacktest.available
        ? '<p class="micro-note"><strong>Modèle contextuel :</strong> ' + contextualBacktest.tested_draws +
          ' tests · ' + Number(contextualBacktest.contextual_average_hits).toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }) +
          '/5 contre ' + Number(contextualBacktest.baseline_average_hits).toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }) +
          '/5 pour l’historique · ' + contextualBacktest.paired_wins + ' victoires, ' + contextualBacktest.paired_losses +
          ' défaites et ' + contextualBacktest.paired_ties + ' égalités · p-Holm vs hasard : ' +
          formatPValue(contextualBacktest.contextual_p_value_vs_random_holm) +
          ' · p-Holm du test apparié : ' + formatPValue(contextualBacktest.paired_sign_p_value_holm) +
          '. ' + escapeHtml(contextualBacktest.warning || "") + '</p>'
        : contextualBacktest && contextualBacktest.reason
          ? '<p class="micro-note">Backtest contextuel : ' + escapeHtml(contextualBacktest.reason) + '</p>' : '';
      $("#backtest-content").innerHTML =
        '<div class="backtest-summary">' +
          '<span><strong>' + comparison.tested_draws + '</strong> prévision(s) hors échantillon par méthode</span>' +
          '<span>Apprentissage initial : ' + comparison.training_draws + ' tirages</span>' +
          '<span>Référence aléatoire : ' + comparison.expected_hits.toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' / 5</span>' +
        '</div>' +
        '<div class="table-scroll"><table class="model-comparison-table">' +
          '<thead><tr><th>MÉTHODE</th><th>TESTS</th><th>MOYENNE OBSERVÉE</th><th>HASARD ATTENDU</th><th>ÉCART</th><th>P-HOLM</th><th>CONFIRMATION</th></tr></thead>' +
          '<tbody>' + methodRows + '</tbody>' +
        '</table></div>' +
        '<p class="micro-note">' + escapeHtml(comparison.methodology || "") +
          ' P-Holm est la probabilité exacte d’obtenir au moins autant de touches sous le modèle aléatoire, après correction des comparaisons multiples. ' +
          escapeHtml(comparison.confirmation_note || "") + ' ' + caveat + '</p>' +
        contextualDetail;
    }

    const forecasts = state.forecastHistory;
    $("#forecast-count").textContent = forecasts.length + " ENREGISTRÉE" + (forecasts.length > 1 ? "S" : "");
    $("#forecast-history-body").innerHTML = forecasts.length ? forecasts.map((item) =>
      '<tr><td>' + formatDate(item.based_on_latest_date) + '<br><small>' + item.based_on_draw_count + ' tirages disponibles</small></td>' +
      '<td><div class="ball-row">' + item.numbers.map((n) => ball(n, false, true)).join("") + '</div></td>' +
      '<td>' + (item.actual_draw_date ? formatDate(item.actual_draw_date) : '<span class="no-repeat">En attente du prochain tirage</span>') + '</td>' +
      '<td>' + (item.actual_numbers ? '<div class="ball-row">' + item.actual_numbers.map((n) => ball(n, item.numbers.includes(n), true)).join("") + '</div>' : "—") + '</td>' +
      '<td>' + (item.evaluated ? '<strong>' + item.hits + '/5</strong>' : "—") + '</td></tr>'
    ).join("") : '<tr><td colspan="5" class="empty-cell">Enregistre ton premier pronostic pour commencer à mesurer le modèle.</td></tr>';
  }


  function renderContextualGroups(rows, selector) {
    const node = $(selector);
    if (!rows || !rows.length) {
      node.innerHTML = '<tr><td colspan="4" class="empty-cell">Aucune donnée disponible pour le moment.</td></tr>';
      return;
    }
    node.innerHTML = rows.map((row) =>
      '<tr><td>' + escapeHtml(row.label) + '</td><td>' + row.draw_count + '</td>' +
      '<td>' + numberFmt.format(row.average_draw_sum) + '</td><td>' +
      numberFmt.format(row.average_odd_count) + '</td></tr>'
    ).join("");
  }

  function renderContextualStudy(data) {
    const meta = data.meta || {};
    const configWarning = $("#context-config-warning");
    $("#context-sample-count").textContent = numberFmt.format(meta.draw_count || 0);
    $("#context-sample-level").textContent = meta.sample_level === "monitoring"
      ? "Suivi élargi · interprétation prudente"
      : meta.sample_level === "exploratory"
        ? "Étude exploratoire · échantillon limité"
        : "Échantillon insuffisant pour conclure";
    $("#context-weather-status").textContent = !meta.location_configured
      ? "À configurer"
      : meta.weather_available ? "Disponible" : "Indisponible";
    $("#context-seismic-status").textContent = !meta.location_configured
      ? "À configurer"
      : meta.seismic_available ? "Disponible" : "Indisponible";
    $("#context-location").textContent = meta.location_name || "Non configuré";
    $("#context-seismic-radius").textContent = meta.seismic_radius_km
      ? "Rayon : " + numberFmt.format(meta.seismic_radius_km) + " km · magnitude ≥ " + numberFmt.format(meta.seismic_min_magnitude)
      : "Événements autour du lieu du tirage";

    const timeNotice = meta.timezone_assumed_utc
      ? " L'heure " + (meta.draw_time || "16:35") + " est provisoirement interprétée en UTC : vérifie DRAW_TIMEZONE dans Render."
      : " Référence horaire : " + (meta.draw_time || "16:35") + " (" + (meta.timezone || "fuseau configuré") + ").";
    const notices = [];
    if (meta.location_is_estimate) {
      notices.push("Lieu provisoire : centre du quartier Antaninarenina à Antananarivo, utilisé comme approximation parce que le site exact n'a pas été confirmé. Vérifie que le tirage correspond bien au Loto 5/35 Bet261 ; remplace DRAW_LOCATION_LAT, DRAW_LOCATION_LON et DRAW_LOCATION_NAME dans Render et règle DRAW_LOCATION_IS_ESTIMATE=false si nécessaire.");
    }
    if (meta.weather_error || meta.seismic_error) {
      notices.push([meta.weather_error, meta.seismic_error].filter(Boolean).join(" "));
    }
    if (meta.timezone_assumed_utc) notices.push(timeNotice.trim());
    if (!meta.location_configured) {
      notices.push("Les coordonnées du lieu du tirage ne sont pas configurées. Ajoute DRAW_LOCATION_LAT et DRAW_LOCATION_LON dans Render > Environment.");
    }
    configWarning.hidden = notices.length === 0;
    configWarning.textContent = notices.join(" ") + (notices.length ? timeNotice : "");

    const correlations = data.correlations || {};
    $("#context-test-count").textContent = (correlations.tests_count || 0) + " TEST" + ((correlations.tests_count || 0) > 1 ? "S" : "");
    $("#context-correlation-method").textContent = (correlations.method || "") + " " + (meta.sample_note || "");
    const results = correlations.results || [];
    $("#context-correlation-body").innerHTML = results.length ? results.map((row) => {
      const isMarked = row.p_adjusted != null && row.p_adjusted <= 0.05;
      return '<tr><td><strong>' + escapeHtml(row.factor_label) + '</strong></td>' +
        '<td>' + escapeHtml(row.outcome_label) + '</td><td>' + row.sample_size + '</td>' +
        '<td>' + Number(row.spearman_rho).toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + '</td>' +
        '<td>' + (row.p_adjusted == null ? "—" : Number(row.p_adjusted).toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 })) + '</td>' +
        '<td><span class="context-result-label ' + (isMarked ? "context-replicate" : "context-neutral") + '">' +
          (isMarked ? "À répliquer" : "Non concluant") + '</span></td></tr>';
    }).join("") : '<tr><td colspan="6" class="empty-cell">' +
      (meta.draw_count < 30 ? "Il faut au moins 30 tirages pour lancer les tests exploratoires." :
        "Aucune corrélation calculable : vérifie les données météo et les coordonnées du lieu.") +
      '</td></tr>';

    renderContextualGroups(data.zodiac_groups || [], "#context-zodiac-body");
    renderContextualGroups(data.moon_groups || [], "#context-moon-body");

    const rows = data.rows || [];
    $("#context-history-body").innerHTML = rows.length ? rows.map((row) => {
      const weather = (value, suffix = "") => value == null ? "—" :
        Number(value).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + suffix;
      const seismicCount = row.earthquake_count == null ? "—" : row.earthquake_count;
      return '<tr><td>' + formatDate(row.date) + '<small>' + escapeHtml(row.reference_time_local || meta.draw_time || "16:35") + '</small></td>' +
        '<td><strong>' + escapeHtml(row.zodiac_sign) + '</strong><small>' + escapeHtml(row.moon_phase) +
        ' · ' + Math.round((row.moon_illumination || 0) * 100) + '%</small></td>' +
        '<td>' + weather(row.temperature_2m_at_draw_hour ?? row.temperature_2m_mean, "°") + '</td>' +
        '<td>' + weather(row.relative_humidity_2m_at_draw_hour ?? row.relative_humidity_2m_mean, " %") + '</td>' +
        '<td>' + weather(row.precipitation_at_draw_hour ?? row.precipitation_sum, " mm") + '</td>' +
        '<td>' + weather(row.pressure_msl_at_draw_hour ?? row.pressure_msl_mean, " hPa") + '</td>' +
        '<td>' + weather(row.wind_speed_10m_at_draw_hour ?? row.wind_speed_10m_max, " km/h") + '</td>' +
        '<td>' + seismicCount + '</td>' +
        '<td>' + weather(row.nearest_distance_km, " km") + '</td>' +
        '<td>' + weather(row.nearest_depth_km, " km") + '</td>' +
        '<td>' + weather(row.max_magnitude) + '</td>' +
        '<td><strong>' + row.draw_sum + '</strong></td></tr>';
    }).join("") : '<tr><td colspan="12" class="empty-cell">Aucun tirage enregistré.</td></tr>';

    $("#context-methodology-note").textContent = [
      data.methodology && data.methodology.astrology,
      data.methodology && data.methodology.astronomy,
      data.methodology && data.methodology.weather,
      data.methodology && data.methodology.seismic,
      data.methodology && data.methodology.prediction_policy
    ].filter(Boolean).join(" ");
  }

  async function loadContextualPrediction(force = false) {
    if (state.contextualPredictionLoading) return false;
    if (state.contextualPrediction && !force) {
      renderPrediction();
      return true;
    }
    state.contextualPredictionLoading = true;
    if (state.analysis) renderPrediction();
    try {
      const result = await api("/api/contextual-prediction" + (force ? "?refresh=1" : ""));
      state.contextualPrediction = result;
      if (state.analysis) {
        const prediction = { ...(state.basePrediction || state.analysis.prediction) };
        state.analysis.prediction = prediction;
        prediction.contextual_model = result;
        prediction.active_model_id = "hybrid";
        const baseModels = (prediction.models || []).filter((model) => model.id !== "contextual");
        if (result.ready) {
          const model = {
            id: "contextual",
            label: "Historique + météo + Lune + sismicité",
            description: "Classement expérimental combinant le passé et les contextes environnementaux comparables.",
            numbers: result.numbers,
            score_index: result.score_index,
            score_note: "Indice relatif et contextuel, pas une probabilité."
          };
          prediction.models = [...baseModels, model];
          prediction.active_model_id = "contextual";
          prediction.numbers = result.numbers;
          prediction.ranked = result.ranked;
          prediction.method = "Historique + météo + Lune + sismicité (expérimental)";
          prediction.alternatives = prediction.models.filter((item) => item.id !== "contextual").map((item) => item.numbers);
          prediction.diverse_scenarios = result.diverse_scenarios || prediction.diverse_scenarios || [];
        } else {
          prediction.models = baseModels;
          prediction.numbers = baseModels.find((item) => item.id === "hybrid")?.numbers || prediction.numbers;
          prediction.ranked = state.analysis.prediction.ranked;
        }
        renderPrediction();
      }
      return true;
    } catch (error) {
      state.contextualPrediction = {
        ready: false,
        reason: "Impossible de charger le modèle contextuel : " + error.message,
        backtest: { available: false, reason: error.message }
      };
      if (state.analysis) {
        if (state.basePrediction) {
          state.analysis.prediction = { ...state.basePrediction, contextual_model: state.contextualPrediction };
        }
        renderPrediction();
      }
      toast("Modèle contextuel indisponible : " + error.message, true);
      return false;
    } finally {
      state.contextualPredictionLoading = false;
    }
  }

  async function loadContextualStudy(force = false) {
    if (state.contextualLoading) return;
    if (state.contextualStudy && !force) {
      renderContextualStudy(state.contextualStudy);
      return;
    }
    state.contextualLoading = true;
    $("#context-correlation-body").innerHTML = '<tr><td colspan="6" class="empty-cell">Récupération des archives météo et du catalogue sismique…</td></tr>';
    try {
      const result = await api("/api/contextual-study");
      state.contextualStudy = result;
      renderContextualStudy(result);
    } catch (error) {
      $("#context-correlation-body").innerHTML = '<tr><td colspan="6" class="empty-cell">' + escapeHtml(error.message) + '</td></tr>';
      toast("Impossible de charger le laboratoire externe : " + error.message, true);
    } finally {
      state.contextualLoading = false;
    }
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
      state.basePrediction = JSON.parse(JSON.stringify(analysis.prediction));
      state.forecastHistory = forecastData.predictions;
      state.contextualPrediction = null;
      renderAll();
      if ($("#view-prediction").classList.contains("active")) loadContextualPrediction(true);
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
    if ($("#context-refresh")) $("#context-refresh").addEventListener("click", () => loadContextualStudy(true));
    if ($("#contextual-prediction-refresh")) $("#contextual-prediction-refresh").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const refreshed = await loadContextualPrediction(true);
        if (refreshed) toast("Modèle contextuel actualisé.");
      } finally {
        button.disabled = false;
      }
    });
    if ($("#logout-button")) {
      $("#logout-button").addEventListener("click", async () => {
        try { await api("/logout", { method: "POST" }); window.location.href = "/login"; }
        catch (error) { toast(error.message, true); }
      });
    }
    const initialView = location.hash.slice(1);
    if (["overview", "history", "analysis", "prediction", "environment"].includes(initialView)) switchView(initialView);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadData();
  });
})();
