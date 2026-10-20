"use strict";
const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [
  ...parent.querySelectorAll(selector),
];
const state = {
  tasks: [],
  materials: [],
  preferences: {},
  history: [],
  health: {},
  filter: "open",
  view: "academic",
  trace: [],
  busy: [],
  sending: false,
};
const names = {
  overview: "Мой пульс",
  academic: "Моя учёба",
  notebook: "Конспекты",
  journey: "Мой путь",
  chat: "AI-ассистент",
  tasks: "Миссии",
  week: "Моя неделя",
  materials: "Материалы",
  practice: "Практика",
  settings: "Подключения и данные",
};
const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  spark:
    '<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6L12 3Z"/>',
  check:
    '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="m8 12 3 3 5-6"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 10h18m-14 4h3m4 0h3m-10 3h3"/>',
  book: '<path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Zm0 0v15"/>',
  settings:
    '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="currentColor"/><circle cx="16" cy="12" r="2" fill="currentColor"/><circle cx="8" cy="18" r="2" fill="currentColor"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  arrow: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>',
  upload: '<path d="M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4"/>',
  activity: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
};
function icon(name) {
  const span = document.createElement("span");
  span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.check}</svg>`;
  return span;
}
$$("[data-icon]").forEach((e) => e.append(icon(e.dataset.icon).firstChild));
function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}
function button(text, fn, cls = "button secondary") {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", fn);
  return b;
}
function toast(text, error = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 6000);
}
async function api(path, options = {}) {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {}
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? "Проверьте обязательные поля и формат даты."
          : `Ошибка запроса (${response.status})`,
    );
  }
  return response.status === 204 ? null : response.json();
}
const plural = (n, forms) => {
  const a = Math.abs(n);
  return !Number.isInteger(a)
    ? forms[1]
    : a % 100 >= 11 && a % 100 <= 14
      ? forms[2]
      : a % 10 === 1
        ? forms[0]
        : a % 10 >= 2 && a % 10 <= 4
          ? forms[1]
          : forms[2];
};
const zone = () => state.preferences.timezone || "Asia/Almaty";
const dateLabel = (iso, options = {}) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    timeZone: zone(),
    ...options,
  }).format(new Date(iso));
const timeLabel = (iso) =>
  new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: zone(),
  }).format(new Date(iso));
function wallTime(iso, tz = zone()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const get = (k) => parts.find((p) => p.type === k).value;
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}
function isoFromWall(value, tz = zone()) {
  if (!value) throw new Error("Укажите дату и время");
  const base = Date.parse(value + "Z");
  let result = base;
  for (let i = 0; i < 3; i++) {
    const observed = Date.parse(wallTime(new Date(result), tz) + "Z");
    result += base - observed;
  }
  if (wallTime(new Date(result), tz) !== value)
    throw new Error("Это время недоступно в выбранном часовом поясе");
  return new Date(result).toISOString();
}
function empty(title, text, action) {
  const box = el("div", "empty");
  const mark = el("div", "empty-icon");
  mark.append(icon("book"));
  box.append(mark, el("h3", "", title), el("p", "", text));
  if (action) box.append(action);
  return box;
}
// Only entries created in this tab belong to the in-app Back button.
// This preserves normal browser Back/Forward without leaving CampusPulse.
const navigation = { initialized: false, index: 0, lastURL: "", session: "", pending: false, revision: 0 };
try {
  navigation.session = sessionStorage.getItem("campuspulse-navigation") || crypto.randomUUID();
  sessionStorage.setItem("campuspulse-navigation", navigation.session);
} catch (_) { navigation.session = String(Date.now()) + Math.random(); }
function ownNavigation(entry = history.state) {
  const value = entry?.campusNavigation;
  return value?.session === navigation.session && names[value.view] ? value : null;
}
function routeContext(view = state.view) {
  return view === "notebook" ? window.CampusNotebook?.navigationState() || null : null;
}
function navigationEntry(view, context, index = navigation.index, scroll = 0) {
  return { campusNavigation: { session: navigation.session, index, view, context, scroll } };
}
function navigationIdentity(context) {
  if (!context) return null;
  if (context.mode === "read") return { mode:"read", note_id:context.note_id };
  if (context.mode === "compose") return {
    mode:"compose", selected:[...(context.selected || [])].sort(), preparing:context.preparing || null,
    title:context.title || "", focus:context.focus || "", style:context.style || "summary",
  };
  return context;
}
function updateBackButton() {
  const back = $("#header-back");
  back.disabled = !navigation.initialized || (navigation.index <= 0 && state.view === "academic");
  back.title = back.disabled ? "Это первый экран" : navigation.index <= 0 ? "К моей учёбе" : "Вернуться к предыдущему экрану";
}
function checkpointNavigation() {
  const current = ownNavigation();
  if (!navigation.initialized || navigation.pending || !current || current.view !== state.view) return;
  history.replaceState(navigationEntry(state.view, routeContext(), current.index, window.scrollY), "");
}
function showView(view, options = {}) {
  if (!names[view]) view = "academic";
  const previousView = state.view;
  const existing = ownNavigation();
  let context = options.context !== undefined ? options.context : view === "notebook" ? routeContext(view) : null;
  let restoring = options.history === "restore";
  let restoreScroll = 0;
  if (!navigation.initialized) {
    navigation.initialized = true;
    if (existing) {
      navigation.index = existing.index;
      if (options.context === undefined && existing.view === view) context = existing.context;
      restoreScroll = existing.scroll || 0;
      restoring = true;
    }
    history.replaceState(navigationEntry(view, context, navigation.index, restoreScroll), "", `#${view}`);
  } else if (restoring) {
    navigation.index = existing?.index || 0;
    context = options.context !== undefined ? options.context : existing?.context || null;
    restoreScroll = existing?.scroll || 0;
    if (!existing) history.replaceState(navigationEntry(view, context), "", `#${view}`);
  } else if (options.history === "adopt") {
    navigation.index += 1;
    history.replaceState(navigationEntry(view, context), "", `#${view}`);
  } else {
    const currentContext = routeContext();
    checkpointNavigation();
    const changed = previousView !== view || JSON.stringify(navigationIdentity(context)) !== JSON.stringify(navigationIdentity(currentContext));
    if (options.history === "replace") history.replaceState(navigationEntry(view, context), "", `#${view}`);
    else if (changed) {
      navigation.index += 1;
      history.pushState(navigationEntry(view, context), "", `#${view}`);
    }
  }
  navigation.lastURL = location.href;
  const revision = ++navigation.revision;
  navigation.pending = true;
  state.view = view;
  if (previousView !== view || restoring) $$("dialog[open]").forEach((dialog) => dialog.close());
  const moreMenu = $(".nav-more");
  if (moreMenu) moreMenu.open = false;
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  $$(".nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
    if (b.dataset.view === view) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $("#page-name").textContent = names[view];
  document.title = names[view] + " · CampusPulse";
  updateBackButton();
  const section = $(`#view-${view}`);
  if (previousView !== view && !options.initial) {
    section.classList.remove("is-entering");
    void section.offsetWidth;
    section.classList.add("is-entering");
  }
  let ready;
  if (view === "week") {
    loadPlan();
    ready = window.CampusCalendar?.load();
  }
  if (view === "academic") ready = window.CampusAcademic?.load();
  if (view === "settings") ready = window.CampusAcademic?.loadDemoStatus();
  if (view === "notebook") ready = context && window.CampusNotebook?.restoreNavigation
    ? window.CampusNotebook.restoreNavigation(context)
    : window.CampusNotebook?.load();
  if (!options.initial) {
    const focus = view === "chat" ? $("#chat-input") : $("h1", section);
    if (focus) { if (view !== "chat") focus.tabIndex = -1; focus.focus({ preventScroll: true }); }
  }
  window.scrollTo({ top: restoring ? restoreScroll : 0, behavior: "instant" });
  return Promise.resolve(ready).then(() => {
    if (state.view !== view || navigation.revision !== revision) return;
    navigation.pending = false;
    if (restoring) window.scrollTo({ top: restoreScroll, behavior: "instant" });
    checkpointNavigation();
  }).catch((error) => {
    if (navigation.revision === revision) navigation.pending = false;
    toast(error.message || "Не удалось открыть экран. Попробуй ещё раз.", true);
  });
}
function navigateBack() {
  if (navigation.index > 0 && ownNavigation()) history.back();
  else if (navigation.initialized && navigation.index <= 0 && state.view !== "academic")
    showView("academic", { history: "replace" });
}
$("#header-back").addEventListener("click", navigateBack);
window.CampusNavigation = { checkpoint: checkpointNavigation, back: navigateBack };
$$("[data-view]").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view)),
);
$$('[data-action="new-task"]').forEach((b) =>
  b.addEventListener("click", () => openTask()),
);
$$("[data-close]").forEach((b) =>
  b.addEventListener("click", () =>
    document.getElementById(b.dataset.close).close(),
  ),
);
$$("[data-prompt]").forEach((b) =>
  b.addEventListener("click", () => {
    showView("chat");
    $("#chat-input").value = b.dataset.prompt;
    $("#chat-input").focus();
  }),
);
window.addEventListener("popstate", () => {
  const route = location.hash.slice(1);
  if (names[route]) showView(route, { history: "restore" });
});
window.addEventListener("hashchange", () => {
  const route = location.hash.slice(1);
  if (!names[route] || navigation.lastURL === location.href) return;
  showView(route, { history: ownNavigation() ? "restore" : "adopt" });
});
document.querySelector(".brand").addEventListener("click", (event) => {
  event.preventDefault();
  showView("academic");
});
document.querySelector(".skip-link").addEventListener("click", (event) => {
  event.preventDefault();
  $("#main").tabIndex = -1;
  $("#main").focus();
});
// Native dialog Escape remains intact; return focus to the control that opened it.
const dialogOrigins = new WeakMap();
document.addEventListener("beforetoggle", (event) => {
  if (event.target instanceof HTMLDialogElement && event.newState === "open")
    dialogOrigins.set(event.target, document.activeElement);
}, true);
document.addEventListener("close", (event) => {
  if (!(event.target instanceof HTMLDialogElement)) return;
  queueMicrotask(() => {
    if ($("dialog[open]")) return;
    const origin = dialogOrigins.get(event.target);
    if (origin?.isConnected && !origin.disabled && !origin.closest("[hidden]")) origin.focus({ preventScroll: true });
  });
}, true);
let navigationScrollTimer;
window.addEventListener("scroll", () => {
  clearTimeout(navigationScrollTimer);
  navigationScrollTimer = setTimeout(checkpointNavigation, 180);
}, { passive: true });
function confirmAction(title, text) {
  return new Promise((resolve) => {
    const d = $("#confirm-dialog");
    $("#confirm-title").textContent = title;
    $("#confirm-text").textContent = text;
    $("#confirm-yes").onclick = () => {
      d.close();
      resolve(true);
    };
    $("#confirm-no").onclick = () => {
      d.close();
      resolve(false);
    };
    d.oncancel = () => resolve(false);
    d.addEventListener("close", () => resolve(false), { once: true });
    d.showModal();
  });
}
async function refresh() {
  const data = await api("/workspace");
  Object.assign(state, data);
  state.busy = [...data.preferences.busy];
  renderOverview();
  renderTasks();
  renderMaterials();
  renderPreferences();
  renderHealth();
  renderProgress();
  window.CampusAcademic?.renderProgress();
  renderFeatures();
}
function deadline(task) {
  const hours = (new Date(task.due_at) - new Date()) / 36e5;
  return el(
    "span",
    "deadline" +
      (hours < 0 && !task.completed
        ? " overdue"
        : hours < 48 && !task.completed
          ? " soon"
          : ""),
    task.completed
      ? "Завершено"
      : hours < 0
        ? "Срок прошёл"
        : dateLabel(task.due_at),
  );
}
function taskRow(task, full = false) {
  const row = el("div", "task-row" + (task.completed ? " task-completed" : ""));
  const check = button(
    task.completed ? "✓" : "",
    async () => {
      try {
        check.disabled = true;
        const before = state.progress?.xp || 0;
        await api("/tasks/" + task.id, {
          method: "PATCH",
          body: JSON.stringify({ completed: !task.completed }),
        });
        await refresh();
        if (state.progress.xp > before) celebrate(state.progress.xp - before);
        else if (task.completed)
          toast("Задание возвращено в работу. Его опыт исключён из суммы.");
      } catch (e) {
        toast(e.message, true);
      } finally {
        check.disabled = false;
      }
    },
    "task-box" + (task.completed ? " done" : ""),
  );
  check.setAttribute(
    "aria-label",
    (task.completed ? "Вернуть в работу: " : "Завершить: ") + task.title,
  );
  const content = el("div", "task-content");
  content.append(
    el("strong", "", task.title),
    el(
      "small",
      "",
      `${task.course} · ${task.estimated_minutes} мин${task.priority === "high" ? " · высокий приоритет" : ""}`,
    ),
  );
  const rewardBox = button(
    "✦ " + task.why.result + " XP",
    () => showWhy(task.why),
    "reward-pill",
  );
  rewardBox.setAttribute(
    "aria-label",
    "Почему награда за «" + task.title + "»: " + task.why.result + " XP",
  );
  row.append(check, content, rewardBox, deadline(task));
  if (full) {
    const actions = el("div", "row-actions");
    actions.append(
      button("Изменить", () => openTask(task), "icon-button small-action"),
      button(
        "Удалить",
        async () => {
          if (
            await confirmAction(
              "Удалить задание?",
              "Удалится только это задание.",
            )
          )
            try {
              await api("/tasks/" + task.id, { method: "DELETE" });
              await refresh();
              toast("Задание удалено");
            } catch (e) {
              toast(e.message, true);
            }
        },
        "icon-button small-action",
      ),
    );
    row.append(actions);
    if (task.source)
      content.append(
        button(
          "Источник задания ↗",
          () => openSource(task.source),
          "text-button",
        ),
      );
  }
  return row;
}
function renderOverview() {
  const open = state.tasks.filter((t) => !t.completed);
  const m = state.metrics;
  $("#stat-open").replaceChildren(
    document.createTextNode(m.open),
    el("span", "", plural(m.open, ["миссия", "миссии", "миссий"])),
  );
  $("#stat-due").replaceChildren(
    document.createTextNode(m.due),
    el("span", "", plural(m.due, ["дедлайн", "дедлайна", "дедлайнов"])),
  );
  $("#stat-hours").replaceChildren(
    document.createTextNode(m.hours.toLocaleString("ru-RU")),
    el("span", "", plural(m.hours, ["час", "часа", "часов"])),
  );
  $("#nav-count").textContent = open.length;
  const overdue = open.filter((t) => new Date(t.due_at) < new Date()).length;
  $("#stat-open-note").textContent = overdue
    ? `${overdue} с прошедшим дедлайном`
    : open.length
      ? "Каждый шаг приближает к цели"
      : "Начни с одного небольшого шага";
  const list = $("#upcoming-list");
  list.replaceChildren();
  if (!open.length)
    list.append(
      empty(
        "Здесь появятся твои задания",
        "Добавь дедлайн — и мы поможем найти время на подготовку.",
        button("Добавить первое задание", () => openTask(), "text-button"),
      ),
    );
  else
    open
      .sort((a, b) => new Date(a.due_at) - new Date(b.due_at))
      .slice(0, 4)
      .forEach((t) => list.append(taskRow(t)));
  $("#top-date").textContent = dateLabel(new Date(), { weekday: "short" });
}
function renderTasks() {
  const search = $("#task-search").value.toLowerCase();
  const tasks = state.tasks
    .filter(
      (t) =>
        (state.filter === "all" ||
          (state.filter === "done" ? t.completed : !t.completed)) &&
        `${t.title} ${t.course}`.toLowerCase().includes(search),
    )
    .sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  const list = $("#task-list");
  list.replaceChildren();
  if (!tasks.length) {
    list.append(
      empty(
        "Пока пусто",
        search
          ? "По этому запросу ничего не найдено."
          : "Добавь задание или измени фильтр.",
        button("Добавить задание", () => openTask()),
      ),
    );
    return;
  }
  const table = el("div", "task-table");
  tasks.forEach((t) => table.append(taskRow(t, true)));
  list.append(table);
}
$$("[data-filter]").forEach((b) =>
  b.addEventListener("click", () => {
    state.filter = b.dataset.filter;
    $$("[data-filter]").forEach((x) => x.classList.toggle("selected", x === b));
    renderTasks();
  }),
);
$("#task-search").addEventListener("input", renderTasks);
function openTask(task = null) {
  $("#task-form").reset();
  $("#task-id").value = task?.id || "";
  $("#task-dialog-title").textContent = task?.id
    ? "Изменить задание"
    : "Добавить задание";
  $("#task-title").value = task?.title || "";
  $("#task-course").value = task?.course || "";
  $("#task-due").value = task?.due_at ? wallTime(task.due_at) : "";
  $("#task-minutes").value = task?.source
    ? (task.estimated_minutes ?? "")
    : task?.estimated_minutes || 60;
  state.taskSource = task?.source || null;
  $("#task-source-preview").replaceChildren();
  if (state.taskSource)
    $("#task-source-preview").append(
      quoteCard(state.taskSource),
      el(
        "p",
        "muted",
        "Проверь цитату и заполни поля. Сохранённые значения будут подтверждены тобой.",
      ),
    );
  $("#task-priority").value = task?.priority || "normal";
  $("#task-notes").value = task?.notes || "";
  $("#task-tz").textContent = zone();
  $("#task-dialog").showModal();
  $("#task-title").focus();
}
$("#task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const b = $("button[type=submit]", event.target);
  if (b.disabled) return;
  b.disabled = true;
  event.target.setAttribute("aria-busy", "true");
  try {
    const id = $("#task-id").value;
    await api("/tasks" + (id ? "/" + id : ""), {
      method: id ? "PUT" : "POST",
      body: JSON.stringify({
        title: $("#task-title").value,
        course: $("#task-course").value,
        due_at: isoFromWall($("#task-due").value),
        estimated_minutes: Number($("#task-minutes").value),
        priority: $("#task-priority").value,
        notes: $("#task-notes").value,
        source: state.taskSource,
      }),
    });
    $("#task-dialog").close();
    await refresh();
    toast("Задание сохранено. Источник: данные вашей формы.");
    if (state.view === "week") await loadPlan();
  } catch (e) {
    toast(e.message, true);
  } finally {
    b.disabled = false;
    event.target.setAttribute("aria-busy", "false");
  }
});
function renderPreferences() {
  const p = state.preferences;
  $("#pref-zone").value = p.timezone;
  $("#pref-minutes").value = p.daily_minutes;
  $("#pref-start").value = p.start_hour;
  $("#pref-end").value = p.end_hour;
  $("#pref-event-minutes").value = p.event_minutes || 60;
  renderBusy();
}
function renderBusy() {
  const list = $("#busy-list");
  list.replaceChildren();
  state.busy.forEach((b, i) => {
    const row = el("div", "busy-row");
    row.append(
      el(
        "span",
        "",
        `${dateLabel(b.start)} ${timeLabel(b.start)} → ${dateLabel(b.end)} ${timeLabel(b.end)}`,
      ),
      button(
        "Убрать",
        () => {
          state.busy.splice(i, 1);
          renderBusy();
        },
        "text-button",
      ),
    );
    list.append(row);
  });
}
$("#add-busy").onclick = () => {
  try {
    const start = isoFromWall($("#busy-start").value, $("#pref-zone").value);
    const end = isoFromWall($("#busy-end").value, $("#pref-zone").value);
    if (end <= start)
      throw new Error("Конец интервала должен быть позже начала");
    if (state.busy.length >= 60) throw new Error("Доступно до 60 интервалов");
    state.busy.push({ start, end });
    renderBusy();
    toast("Интервал добавлен. Нажмите «Обновить план»");
  } catch (e) {
    toast(e.message, true);
  }
};
$("#preferences-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    state.preferences = await api("/preferences", {
      method: "PUT",
      body: JSON.stringify({
        timezone: $("#pref-zone").value,
        daily_minutes: Number($("#pref-minutes").value),
        start_hour: Number($("#pref-start").value),
        end_hour: Number($("#pref-end").value),
        busy: state.busy,
        event_minutes: Number($("#pref-event-minutes").value),
      }),
    });
    await loadPlan();
    await refresh();
    toast("План обновлён по сохранённым настройкам доступности.");
  } catch (e) {
    toast(e.message, true);
  }
});
async function loadPlan() {
  try {
    const p = await api("/plan");
    if (p.calendar) {
      state.calendar_cache = p.calendar;
      renderCalendar();
    }
    $("#plan-summary").textContent =
      `${p.scheduled_minutes} минут запланировано · ${p.sessions.length} ${plural(p.sessions.length, ["учебный блок", "учебных блока", "учебных блоков"])} · ${p.timezone}`;
    $("#plan-summary").append(whyButton(p.why));
    const risks = $("#plan-risks");
    risks.replaceChildren();
    p.risks.forEach((r) => {
      const box = el(
        "div",
        "risk",
        `${r.title}: ${r.reason}. Осталось ${r.unscheduled_minutes} мин.`,
      );
      box.append(whyButton(r.why));
      risks.append(box);
    });
    const grid = $("#week-grid");
    grid.replaceChildren();
    const today = wallTime(new Date()).slice(0, 10);
    for (let d = 0; d < 7; d++) {
      const day = new Date(today + "T12:00:00Z");
      day.setUTCDate(day.getUTCDate() + d);
      const key = day.toISOString().slice(0, 10);
      const col = el("article", "day-column" + (d === 0 ? " today" : ""));
      const head = el(
        "div",
        "day-header",
        dateLabel(day, { weekday: "long", day: undefined, month: undefined }),
      );
      head.append(el("strong", "", dateLabel(day)));
      col.append(head);
      const sessions = p.sessions.filter((s) =>
        wallTime(s.start).startsWith(key),
      );
      if (!sessions.length)
        col.append(el("div", "day-empty", "Нет учебных блоков"));
      sessions.forEach((s) => {
        const block = el(
          "div",
          "study-block",
          `${timeLabel(s.start)} — ${timeLabel(s.end)}`,
        );
        block.append(el("strong", "", s.title), el("small", "", s.course));
        block.append(whyButton(s.why));
        col.append(block);
      });
      grid.append(col);
    }
  } catch (e) {
    toast(e.message, true);
  }
}
$("#material-upload").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  event.target.disabled = true;
  toast("Читаю материал…");
  try {
    await api("/materials", { method: "POST", body: form });
    await refresh();
    toast("Материал добавлен. Текст извлечён из выбранного файла.");
  } catch (e) {
    toast(e.message, true);
  } finally {
    event.target.disabled = false;
    event.target.value = "";
  }
});
function renderMaterials() {
  const list = $("#material-list");
  list.replaceChildren();
  if (!state.materials.length) {
    list.append(empty("Здесь будет твоя база знаний", "Загрузи PDF с текстом или вставь конспект. Поиск покажет точную страницу и строку, а тренировка поможет повторить термины.", button("Вставить первый конспект", openNoteDialog)));
  }
  state.materials.forEach((m) => {
    const card = el("article", "material-card");
    const mark = el("div", "file-icon");
    mark.append(icon("book"));
    const info = el("div");
    info.append(
      el("strong", "", m.name),
      el("small", "", `${m.page_count} стр. · ${dateLabel(m.uploaded_at)}`),
    );
    info.append(
      button("Открыть", async () => {
        try {
          const doc = await api("/materials/" + m.id);
          $("#material-name").textContent = doc.name;
          const content = $("#material-content");
          content.replaceChildren();
          doc.pages.forEach((p) => {
            const section = el("section");
            section.append(
              el("strong", "", `Страница ${p.page}`),
              el(
                "pre",
                "",
                p.text
                  .split("\n")
                  .map((line, i) => `${i + 1} │ ${line}`)
                  .join("\n"),
              ),
            );
            content.append(section);
          });
          $("#material-dialog").showModal();
        } catch (e) {
          toast(e.message, true);
        }
      }),
      button("Разобрать силлабус", () => showSyllabus(m)),
      button("Добавить предмет", () => {
        showView("academic");
        window.CampusAcademic?.importMaterial(m.id);
      }),
      button("Квест по материалу", () => {
        showView("practice");
        selectPractice("quests");
        $("#quest-material").value = m.id;
        $("#quest-source-form").requestSubmit();
      }),
      button("Обсудить", () => {
        showView("chat");
        $("#chat-input").value =
          `Объясни основные идеи материала «${m.name}». Укажи страницы.`;
      }),
      button("Удалить", async () => {
        if (await confirmAction("Удалить материал?", m.name))
          try {
            await api("/materials/" + m.id, { method: "DELETE" });
            await refresh();
          } catch (e) {
            toast(e.message, true);
          }
      }),
    );
    card.append(mark, info);
    list.append(card);
  });
}
function renderHealth() {
  const h = state.health;
  const title =
    h.mode === "tools"
      ? "Google Gemini ожидает подключения"
      : h.mode === "remote"
        ? "Agent Engine"
        : h.gemini_provider === "developer_api"
          ? "Gemini · Google AI Studio"
          : "Gemini · Vertex AI";
  $("strong", $("#mode-banner")).textContent = title;
  $(":scope > div > span", $("#mode-banner")).textContent =
    h.mode === "tools"
      ? "Формулы, поиск, квесты и календарный диалог доступны без ИИ."
      : "Ответы с источниками. Успешный вызов подтверждается журналом.";
  $("#chat-mode").textContent = title + ". Доступ настроен на сервере; подключение проверяется при запросе.";
  if (h.mode === "tools") $("#chat-mode").textContent = "Учебные инструменты доступны · Gemini ещё не подключён. Поиск, формулы, цели и план работают сейчас.";
  $$("[data-processing]").forEach((item) => {
    item.textContent = h.mode === "tools"
      ? "Локальная обработка · без отправки в Gemini."
      : item.dataset.processing === "documents"
        ? "При включённом Gemini выбранный документ может отправляться Google для распознавания. Не загружай личные секреты."
        : "При включённом Gemini выбранные фрагменты отправляются Google для подготовки конспекта. Не загружай личные секреты.";
  });
  const cards = $("#integration-cards");
  cards.replaceChildren();
  [
    [
      "Google Gemini",
      h.mode === "remote"
        ? "Облачный агент Google Cloud. Сервер обращается к развёрнутому Agent Engine."
        : h.gemini_provider === "developer_api"
          ? "Gemini через Google AI Studio. Серверный ключ не показывается в браузере."
          : h.mode === "tools"
            ? "Формулы, план и работа с материалами доступны локально. Gemini можно подключить отдельно."
            : "Gemini через Vertex AI. Сервер использует авторизацию Google Cloud.",
      h.mode === "tools"
        ? "Gemini не подключён"
        : "Настроен; доступ проверяется при запросе",
    ],
    [
      "Google Calendar",
      "События основного календаря, уточнение даты и времени, проверка пересечений.",
      state.google?.connected
        ? "Разрешение сохранено"
        : state.google?.configured ? "Можно подключить Google" : "Доступен экспорт .ics · вход Google ещё не настроен",
    ],
    [
      "MCP и собственные функции",
      "Часы сервера, точные цитаты, формулы, синтаксический анализ и журнал действий.",
      "Вычисления выполняет код",
    ],
  ].forEach(([title, desc, status]) => {
    const card = el("article", "integration-card");
    card.append(
      el("h2", "", title),
      el("p", "", desc),
      el("span", "connection-status", status),
    );
    cards.append(card);
  });
}

function appendSafeText(parent, text) {
  const pattern = /https:\/\/github\.com\/[A-Za-z0-9_.\/-]+/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    parent.append(document.createTextNode(text.slice(last, match.index)));
    const a = el("a", "", match[0]);
    a.href = match[0];
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    parent.append(a);
    last = match.index + match[0].length;
  }
  parent.append(document.createTextNode(text.slice(last)));
}
function addMessage(
  role,
  text,
  proposals = [],
  evidence = [],
  why = null,
  calendar = null,
) {
  const area = $("#messages");
  $(".chat-welcome", area)?.remove();
  const message = el("article", "message " + role);
  const meta = el(
    "div",
    "message-meta",
    role === "user" ? "ТЫ" : role === "error" ? "ПОДКЛЮЧЕНИЕ" : "CAMPUSPULSE",
  );
  const body = el("div", "message-body");
  appendSafeText(body, text);
  message.append(meta, body);
  if (role !== "user") {
    message.append(
      whyButton(
        why || {
          title: "Почему это сообщение",
          source: "Проверка подключения и доступных источников",
          result: text,
        },
      ),
    );
    if (evidence.length) {
      const sources = el("div", "answer-sources");
      sources.append(el("small", "", "ПРОВЕРИТЬ ИСТОЧНИКИ"));
      evidence.forEach((f) =>
        sources.append(
          button(f.title + " ↗", () => showWhy(f.why), "source-chip"),
        ),
      );
      message.append(sources);
    }
  }
  if (calendar?.status === "created" && safeCalendarUrl(calendar.url)) {
    const link = el(
      "a",
      "button secondary",
      "Открыть событие в Google Calendar ↗",
    );
    link.href = calendar.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    message.append(link);
  }
  proposals.forEach((p) => {
    const box = el("div", "proposal");
    box.append(
      el("strong", "", "Предложение: " + p.title),
      el(
        "p",
        "muted",
        `${p.course} · ${dateLabel(p.due_at)} ${timeLabel(p.due_at)} · ${p.estimated_minutes} мин`,
      ),
      button("Проверить и сохранить", () => openTask(p)),
    );
    message.append(box);
  });
  area.append(message);
  area.scrollTop = area.scrollHeight;
  return message;
}
function renderHistory() {
  const area = $("#messages");
  area.replaceChildren();
  if (state.history.length) {
    state.history.forEach((m) =>
      addMessage(
        m.role === "user" ? "user" : "assistant",
        m.text,
        [],
        m.evidence || [],
        m.why,
        m.calendar,
      ),
    );
    return;
  }
  const welcome = el("div", "chat-welcome");
  welcome.append(
    el("div", "spark", "✳"),
    el("h2", "", "Что сейчас важнее всего?"),
    el(
      "p",
      "",
      "Начни с одного вопроса. Проверим данные, выберем инструменты и найдём следующий шаг.",
    ),
  );
  [
    "Какие предметы сейчас требуют внимания?",
    "Составь план моей учебной недели",
    "Сколько нужно набрать для цели 90?",
    "Найди определение в моих материалах",
    "Запланируй подготовку к экзамену завтра в 18:00",
  ].forEach((p) =>
    welcome.append(
      button(p, () => {
        $("#chat-input").value = p;
        $("#chat-input").focus();
      }),
    ),
  );
  area.append(welcome);
}
function renderTrace(trace) {
  state.trace = trace;
  $("#export-trace").disabled = !trace.length;
  const list = $("#trace-list");
  list.replaceChildren();
  if (!trace.length) {
    list.append(
      el("p", "muted", "Этот ответ не потребовал вызова инструментов."),
    );
    return;
  }
  trace.forEach((t) => {
    const step = el(
      "div",
      "trace-step" + (t.status === "error" ? " error" : ""),
    );
    step.append(
      el("strong", "", t.label),
      el("small", "", `${t.transport} · ${t.elapsed_ms} мс`),
      el("small", "", t.selection || "Выбор модели"),
    );
    const details = el("details");
    details.append(
      el(
        "summary",
        "",
        t.tool + " · " + (t.status === "ok" ? "выполнено" : "ошибка"),
      ),
      el(
        "pre",
        "",
        JSON.stringify({ arguments: t.arguments, result: t.result }, null, 2),
      ),
    );
    step.append(details);
    list.append(step);
  });
}
$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.sending) return;
  const message = $("#chat-input").value.trim();
  if (!message) return;
  state.sending = true;
  $(".send-button").disabled = true;
  $("#chat-input").value = "";
  addMessage("user", message);
  const busy = el("div", "thinking", "Проверяю запрос и вызываю инструменты…");
  $("#messages").append(busy);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  try {
    const result = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    busy.remove();
    addMessage(
      "assistant",
      result.answer,
      result.proposals || [],
      result.evidence || [],
      result.why,
      result.calendar,
    );
    renderTrace(result.trace);
    await refresh();
    $("#chat-mode").textContent =
      result.mode === "command"
        ? "Календарный диалог · явная команда и проверка данных"
        : result.mode === "tools"
          ? "Команда выполнена без ИИ · реальные инструменты"
          : `Ответ получен · ${result.model} · ${result.mode === "remote" ? "Google Cloud Agent Engine" : "Gemini"}`;
  } catch (e) {
    busy.remove();
    addMessage("error", e.message);
    renderTrace([]);
  } finally {
    state.sending = false;
    $(".send-button").disabled = false;
    $("#chat-input").focus();
  }
});
$("#chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("#chat-form").requestSubmit();
  }
});
$("#export-trace").onclick = () => {
  const blob = new Blob(
    [
      JSON.stringify(
        {
          exported_at: new Date().toISOString(),
          mode: state.health.mode,
          trace: state.trace,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob);
  const link = el("a");
  link.href = url;
  link.download = "campuspulse-trace.json";
  link.click();
  URL.revokeObjectURL(url);
};
$("#add-demo").onclick = async () => {
  if (await window.CampusAcademic?.changeDemo()) showView("academic");
};
$("#remove-demo").onclick = () => window.CampusAcademic?.changeDemo(true);
$("#clear-data").onclick = async () => {
  if (
    !(await confirmAction(
      "Удалить мои данные?",
      "Задания, материалы и история этого пространства будут удалены. Отменить действие нельзя.",
    ))
  )
    return;
  try {
    await api("/workspace", { method: "DELETE" });
    await refresh();
    renderHistory();
    renderTrace([]);
    toast("Данные удалены");
  } catch (e) {
    toast(e.message, true);
  }
};
async function start() {
  initGame();
  initFeatures();
  try {
    state.health = await api("/health");
    await refresh();
    renderHistory();
    showView(location.hash.slice(1) || "academic", { initial: true, history: "restore" });
  } catch (e) {
    toast("Не удалось загрузить приложение: " + e.message, true);
    $("#mode-banner").textContent =
      "Сервер недоступен. Перезапустите приложение и обновите страницу.";
  }
}
start();
