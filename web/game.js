/* UI renders server-authored game rules; there is no reward calculator here. */
function showWhy(p) {
  if (!p) return;
  $("#why-title").textContent = p.title || "Почему?";
  const body = $("#why-content");
  body.replaceChildren();
  const section = (label, value, code = false) => {
    if (value === undefined || value === "") return;
    const box = el("section", "proof-section");
    box.append(
      el("h3", "", label),
      el(
        code ? "pre" : "p",
        "",
        typeof value === "boolean"
          ? value
            ? "Условие выполнено"
            : "Условие ещё не выполнено"
          : typeof value === "object"
            ? JSON.stringify(value, null, 2)
            : String(value),
      ),
    );
    body.append(box);
  };
  section("Правило / формула", p.formula);
  section("Исходные данные", p.inputs, true);
  section("Результат", p.result, typeof p.result === "object");
  section("Источник", p.source);
  section("Как это понимать", p.note);
  if (safeCalendarUrl(p.source)) {
    const a = el("a", "button secondary", "Открыть источник ↗");
    a.href = p.source;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    body.append(a);
  }
  $("#why-dialog").showModal();
}
function whyButton(proof, label = "Почему?") {
  return button(label, () => showWhy(proof), "why-button");
}
function renderProgress() {
  const p = state.progress;
  if (!p) return;
  $("#top-level").textContent = "✦ Уровень " + p.level;
  $("#hero-level").textContent = "УРОВЕНЬ " + p.level;
  $("#hero-title").textContent =
    p.completed === 0 ? "Начало большого пути" : "Ты уже в движении";
  $("#hero-xp").textContent = p.xp + " XP";
  $("#hero-next").textContent =
    "До следующего уровня: " + p.next_level_xp + " XP";
  $("#hero-progress").value = p.level_progress;
  $("#hero-why").onclick = () =>
    showWhy({
      ...p.why.level,
      inputs: { ...p.why.level.inputs, начисления: p.why.xp.inputs },
      note: p.why.xp.note,
    });
  $("#weekly-count").textContent = p.weekly_completed + " / " + p.weekly_target;
  $("#weekly-progress").value = p.weekly_percent;
  $("#weekly-why").onclick = () => showWhy(p.why.weekly);
  const stats = $("#journey-stats");
  stats.replaceChildren();
  [
    ["Накопленный опыт", p.xp + " XP", "xp"],
    ["Твой уровень", p.level, "level"],
    ["Серия дней", p.streak, "streak"],
  ].forEach(([title, n, key]) => {
    const card = el("article", "stat");
    card.append(
      el("span", "stat-label", title),
      el("strong", "", n),
      whyButton(p.why[key]),
    );
    stats.append(card);
  });
  const nodes = $("#path-nodes");
  const badges = $("#badge-grid");
  nodes.replaceChildren();
  badges.replaceChildren();
  p.badges.forEach((b, i) => {
    const node = button(
      "",
      () => showWhy(b.why),
      "path-node" + (b.unlocked ? " unlocked" : ""),
    );
    node.append(
      el("span", "node-icon", b.unlocked ? "✓" : b.mark),
      el("strong", "", b.name),
      el(
        "small",
        "",
        b.target + " " + plural(b.target, ["миссия", "миссии", "миссий"]),
      ),
    );
    node.setAttribute(
      "aria-label",
      b.name +
        ": " +
        (b.unlocked
          ? "открыто"
          : "нужно " +
            b.target +
            " " +
            plural(b.target, ["задание", "задания", "заданий"])) +
        ". Почему?",
    );
    nodes.append(node);
    const badge = button(
      "",
      () => showWhy(b.why),
      "badge-card" + (b.unlocked ? " unlocked" : " locked"),
    );
    badge.append(
      el("span", "badge-mark badge-" + i, b.mark),
      el("strong", "", b.name),
      el(
        "small",
        "",
        b.unlocked
          ? "Открыто · посмотреть почему"
          : `Отмечено ${b.current} из ${b.target} заданий`,
      ),
    );
    badges.append(badge);
  });
  const ledger = $("#xp-ledger");
  ledger.replaceChildren();
  if (!p.ledger.length)
    ledger.append(
      empty(
        "Первая награда впереди",
        "Заверши задание — здесь появится начисление с формулой.",
      ),
    );
  p.ledger.forEach((entry) => {
    const row = el("div", "ledger-row");
    const info = el("div");
    info.append(
      el("strong", "", entry.title),
      el("small", "muted", dateLabel(entry.at) + " · " + timeLabel(entry.at)),
    );
    row.append(
      info,
      el("b", "xp-earned", "+" + entry.xp + " XP"),
      whyButton(entry.why),
    );
    ledger.append(row);
  });
}
function celebrate(xp) {
  const banner = $("#celebration");
  banner.replaceChildren(
    el("span", "reward-star", "✦"),
    el("strong", "", "+" + xp + " XP · шаг сделан!"),
    el("small", "", "Начисление видно в «Моём пути»"),
  );
  banner.hidden = false;
  clearTimeout(celebrate.timer);
  celebrate.timer = setTimeout(() => (banner.hidden = true), 3500);
}
const focusTimer = {
  duration: 25 * 60,
  remaining: 25 * 60,
  end: null,
  interval: null,
};
function renderFocus() {
  if (focusTimer.end !== null)
    focusTimer.remaining = Math.max(
      0,
      Math.ceil((focusTimer.end - Date.now()) / 1000),
    );
  $("#focus-time").textContent =
    String(Math.floor(focusTimer.remaining / 60)).padStart(2, "0") +
    ":" +
    String(focusTimer.remaining % 60).padStart(2, "0");
  if (focusTimer.end !== null && focusTimer.remaining === 0) {
    focusTimer.end = null;
    clearInterval(focusTimer.interval);
    toast(
      "Фокус-сессия завершена. Таймер достиг нуля; опыт за таймер не начисляется.",
    );
  }
  $("#focus-state").textContent =
    focusTimer.remaining === 0
      ? "время сделать перерыв"
      : focusTimer.end !== null
        ? "ты в своём ритме"
        : focusTimer.remaining < focusTimer.duration
          ? "пауза — это нормально"
          : "готовы начать?";
  $("#focus-toggle").textContent =
    focusTimer.end !== null
      ? "Пауза"
      : focusTimer.remaining === 0
        ? "Ещё сессия"
        : focusTimer.remaining < focusTimer.duration
          ? "Продолжить"
          : "Начать фокус";
  $(".focus-card").classList.toggle("running", focusTimer.end !== null);
}
function initGame() {
  $$("[data-metric]").forEach(
    (b) => (b.onclick = () => showWhy(state.metrics.why[b.dataset.metric])),
  );
  $("#rules-open").onclick = () =>
    showWhy({
      title: "Правила твоего пути",
      formula:
        "XP задания = 20 + min(40, 5 × ceil(минуты / 30)); уровень = 1 + floor(XP / 100)",
      inputs: { пороги_достижений: [1, 3, 5, 10, 20], цель_недели: 3 },
      result: "Баллы только за отмеченные выполненными задания",
      source: "Правила продукта progress-v1 → campuspulse/progress.py",
      note: "Длительность фиксируется при первом завершении. Возврат в работу и удаление убирают XP. Повторное завершение не создаёт новую награду. Нет штрафов, рейтинга других людей или оценки способностей. Завершение подтверждает сам студент.",
    });
  $("#focus-why").onclick = () =>
    showWhy({
      title: "Как работает таймер",
      formula:
        "остаток секунд = max(0, ceil((время окончания − текущее время) / 1000))",
      inputs: { длительность_секунд: focusTimer.duration },
      result: focusTimer.remaining + " секунд",
      source: "Часы этого браузера → web/game.js → renderFocus",
      note: "25 минут — фиксированная настройка продукта, не индивидуальная рекомендация ИИ. Таймер не подтверждает обучение и не начисляет опыт. Перезагрузка сбрасывает сессию.",
    });
  $("#focus-toggle").onclick = () => {
    if (focusTimer.end !== null) {
      renderFocus();
      focusTimer.end = null;
      clearInterval(focusTimer.interval);
    } else {
      if (!focusTimer.remaining) focusTimer.remaining = focusTimer.duration;
      focusTimer.end = Date.now() + focusTimer.remaining * 1000;
      focusTimer.interval = setInterval(renderFocus, 250);
    }
    renderFocus();
  };
  $("#focus-reset").onclick = () => {
    clearInterval(focusTimer.interval);
    focusTimer.end = null;
    focusTimer.remaining = focusTimer.duration;
    renderFocus();
  };
}
