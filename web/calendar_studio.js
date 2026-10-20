"use strict";

/* Real local, Google and study events share one calendar. All labels are text. */
(() => {
  const q = (selector, parent = document) => parent.querySelector(selector);
  const make = (tag, className, content) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (content !== undefined) item.textContent = String(content);
    return item;
  };
  const button = (label, callback, className = "button secondary") => {
    const item = make("button", className, label);
    item.type = "button";
    item.addEventListener("click", callback);
    return item;
  };
  const kinds = { local: "Мои события", google: "Google", study: "Подготовка", deadline: "Дедлайны", imported: "Расписание" };
  const categories = { event: "Событие", important: "Важное дело", class: "Занятие" };
  const model = { month: "", day: "", view: "week", autoDay: true, data: null, editing: null, request: null, requestId: null, loadedAt: 0, loadKey: "", token: 0 };
  let mounted = false;
  const timezone = () => model.data?.timezone || "Asia/Almaty";
  const dateParts = (value, zone = timezone()) => {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return null;
    return Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date).map(part => [part.type, part.value]));
  };
  const dateKey = (value) => {
    const parts = dateParts(value);
    return parts ? `${parts.year}-${parts.month}-${parts.day}` : "";
  };
  const inputDate = (value) => {
    const parts = dateParts(value);
    return parts ? `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}` : "";
  };
  const today = () => dateKey(new Date());
  const calendarDate = (key) => new Date(`${key}T12:00:00Z`);
  const readableDay = (key) => new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", weekday: "long", timeZone: "UTC" }).format(calendarDate(key));
  const readableMonth = (month) => new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric", timeZone: "UTC" }).format(calendarDate(`${month}-01`));
  const clock = (value) => new Intl.DateTimeFormat("ru-RU", { timeZone: timezone(), hour: "2-digit", minute: "2-digit" }).format(new Date(value));
  const report = (message, error = false) => {
    const target = q("#campus-calendar-message");
    if (target) { target.textContent = message; target.classList.toggle("is-error", error); }
    if (error && typeof toast === "function") toast(message, true);
  };
  const request = async (path, method = "GET", body) => {
    const response = await fetch(`/api/calendar${path}`, { method, headers: body === undefined ? {} : { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch (_) { /* Keep the ordinary HTTP error. */ }
      const error = new Error(typeof detail === "string" ? detail : `Не удалось обновить календарь (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  };
  const isoDate = (value) => {
    if (!value) throw new Error("Укажи дату и время.");
    if (typeof isoFromWall === "function") return isoFromWall(value, timezone());
    // Resolve the wall-clock input in the calendar's zone, not the browser zone.
    const target = new Date(`${value}:00Z`).getTime();
    let candidate = target;
    for (let i = 0; i < 3; i += 1) {
      const part = dateParts(candidate);
      const observed = Date.parse(`${part.year}-${part.month}-${part.day}T${part.hour}:${part.minute}:00Z`);
      candidate += target - observed;
    }
    if (inputDate(candidate) !== value) throw new Error("Это время недоступно в выбранном часовом поясе. Выбери другое.");
    return new Date(candidate).toISOString();
  };
  const safeGoogleUrl = (value) => {
    try {
      const url = new URL(value);
      return url.protocol === "https:" && (url.hostname === "calendar.google.com" || (url.hostname === "www.google.com" && url.pathname.startsWith("/calendar"))) ? url.href : null;
    } catch (_) { return null; }
  };
  const events = () => (model.data?.events || []).filter(event => event.start && Number.isFinite(new Date(event.start).getTime()));
  const onDay = (event, day) => {
    const start = dateKey(event.start);
    const finish = new Date(event.end || event.start).getTime();
    const last = dateKey(Math.max(new Date(event.start).getTime(), finish - 1));
    return start <= day && day <= last;
  };
  const dayEvents = (day) => events().filter(event => onDay(event, day)).sort((a, b) => new Date(a.start) - new Date(b.start) || String(a.title).localeCompare(String(b.title), "ru"));
  const eventKind = (event) => Object.hasOwn(kinds, event.kind) ? event.kind : "local";
  const eventTime = (event) => event.all_day ? "Весь день" : `${clock(event.start)}${event.end && new Date(event.end) > new Date(event.start) ? `–${clock(event.end)}` : ""}`;
  const goMonth = (delta) => {
    model.autoDay = false;
    if (model.view === "week") {
      const next = calendarDate(model.day); next.setUTCDate(next.getUTCDate() + delta * 7);
      model.day = next.toISOString().slice(0, 10); model.month = model.day.slice(0, 7);
      load(true); return;
    }
    const current = calendarDate(`${model.month}-01`);
    current.setUTCMonth(current.getUTCMonth() + delta);
    model.month = current.toISOString().slice(0, 7);
    model.day = `${model.month}-01`;
    load(true);
  };
  const selectDay = (day) => {
    model.autoDay = false;
    model.day = day;
    if (!day.startsWith(model.month)) { model.month = day.slice(0, 7); load(true); }
    else render();
  };

  function mount() {
    if (mounted) return true;
    const view = q("#view-week");
    if (!view) return false;
    const section = make("section", "campus-calendar");
    section.id = "campus-calendar";
    section.setAttribute("aria-labelledby", "campus-calendar-title");
    section.innerHTML = `<div class="campus-calendar-heading"><div><div class="eyebrow">ТВОЙ ДЕНЬ, ТВОЙ РИТМ</div><h2 id="campus-calendar-title">Календарь<span>.</span></h2><p>События, занятия и подготовка в одном месте.</p></div><div class="campus-calendar-actions"><a class="button secondary" id="campus-calendar-export" href="/api/calendar/export.ics">↓ .ics</a><button class="button primary" id="campus-calendar-add" type="button">+ Событие</button></div></div><div class="campus-calendar-toolbar"><div class="campus-month-navigation"><button id="campus-calendar-prev" class="icon-button" type="button" aria-label="Предыдущий месяц">‹</button><h3 id="campus-calendar-month"></h3><button id="campus-calendar-next" class="icon-button" type="button" aria-label="Следующий месяц">›</button><button class="text-button" id="campus-calendar-today" type="button">Сегодня</button></div><div class="campus-calendar-connection"><span id="campus-calendar-connection"></span><button class="text-button" id="campus-calendar-refresh" type="button" aria-label="Обновить календарь">↻ Обновить</button></div></div><p id="campus-calendar-message" class="campus-calendar-message" role="status" aria-live="polite"></p><div class="campus-calendar-layout"><div class="campus-calendar-month"><div class="campus-weekdays" aria-hidden="true"><span>Пн</span><span>Вт</span><span>Ср</span><span>Чт</span><span>Пт</span><span>Сб</span><span>Вс</span></div><div id="campus-calendar-grid" class="campus-calendar-grid" role="grid" aria-label="Календарь месяца"></div><div id="campus-calendar-legend" class="campus-calendar-legend"></div></div><aside class="campus-calendar-agenda" aria-labelledby="campus-calendar-day"><div class="eyebrow">ПЛАН НА ДЕНЬ</div><h3 id="campus-calendar-day"></h3><p id="campus-calendar-day-count"></p><div id="campus-calendar-agenda"></div><button class="text-button" id="campus-calendar-day-add" type="button">+ Добавить на этот день</button></aside></div><div class="campus-calendar-footer"><span id="campus-calendar-zone"></span><a href="https://calendar.google.com/calendar/u/0/r" target="_blank" rel="noopener noreferrer">Открыть Google Calendar ↗</a></div>`;
    view.insertBefore(section, view.firstChild);
    const modes = make("div", "campus-calendar-modes");
    modes.setAttribute("aria-label", "Вид календаря");
    for (const [value, title] of [["week", "Неделя"], ["month", "Месяц"]]) {
      const toggle = button(title, () => { model.view = value; render(); }, "campus-calendar-mode");
      toggle.dataset.calendarView = value;
      modes.append(toggle);
    }
    q(".campus-calendar-toolbar", section).insertBefore(modes, q(".campus-calendar-connection", section));
    const information = make("details", "campus-calendar-information");
    information.append(make("summary", "", "Подробнее об источниках и расписании"), q("#campus-calendar-legend", section), q(".campus-calendar-footer", section));
    section.append(information);
    const editor = make("dialog", "campus-calendar-dialog");
    editor.id = "campus-calendar-editor";
    editor.setAttribute("aria-labelledby", "campus-calendar-editor-title");
    editor.innerHTML = `<form id="campus-calendar-form"><div class="campus-calendar-dialog-heading"><div><div class="eyebrow">МЕСТО ДЛЯ ВАЖНОГО</div><h2 id="campus-calendar-editor-title">Новое событие</h2></div><button type="button" class="icon-button" id="campus-calendar-editor-close" aria-label="Закрыть">×</button></div><label>Название<input id="campus-event-title" maxlength="160" placeholder="Например, подготовка к Midterm" required></label><div class="campus-calendar-form-row"><label>Начало<input id="campus-event-start" type="datetime-local" required></label><label>Окончание<input id="campus-event-end" type="datetime-local" required></label></div><p id="campus-event-zone" class="campus-calendar-form-note"></p><div class="campus-calendar-form-row"><label>Тип<select id="campus-event-category"><option value="event">Событие</option><option value="important">Важное дело</option><option value="class">Занятие</option></select></label><label>Сохранить в<select id="campus-event-target"><option value="local">CampusPulse</option><option value="google">CampusPulse + Google Calendar</option></select></label></div><label>Описание<textarea id="campus-event-description" rows="3" maxlength="2000" placeholder="Что стоит подготовить или взять с собой"></textarea></label><label class="campus-calendar-checkbox"><input id="campus-event-busy" type="checkbox" checked><span>Считать это время занятым при составлении плана</span></label><div class="campus-calendar-form-row"><label>Повторение<select id="campus-event-repeat"><option value="none">Без повторения</option><option value="weekly">Каждую неделю</option></select></label><label id="campus-event-until-label" hidden>Повторять до<input id="campus-event-until" type="date"></label></div><p id="campus-event-google-note" class="campus-calendar-form-note"></p><p id="campus-event-error" class="campus-calendar-form-error" role="alert"></p><div class="campus-calendar-dialog-footer"><button type="button" class="button secondary" id="campus-calendar-editor-cancel">Отмена</button><button type="submit" class="button primary" id="campus-event-submit">Сохранить событие</button></div></form>`;
    const detail = make("dialog", "campus-calendar-dialog campus-calendar-detail");
    detail.id = "campus-calendar-detail";
    detail.setAttribute("aria-labelledby", "campus-calendar-detail-title");
    detail.innerHTML = `<div class="campus-calendar-dialog-heading"><div><div id="campus-calendar-detail-source" class="eyebrow"></div><h2 id="campus-calendar-detail-title"></h2></div><button type="button" class="icon-button" id="campus-calendar-detail-close" aria-label="Закрыть">×</button></div><div id="campus-calendar-detail-content"></div><div id="campus-calendar-detail-actions" class="campus-calendar-dialog-footer"></div>`;
    document.body.append(editor, detail);
    q("#campus-calendar-prev").addEventListener("click", () => goMonth(-1));
    q("#campus-calendar-next").addEventListener("click", () => goMonth(1));
    q("#campus-calendar-today").addEventListener("click", () => { model.autoDay = false; model.day = today(); model.month = model.day.slice(0, 7); load(true); });
    q("#campus-calendar-refresh").addEventListener("click", () => load(true));
    q("#campus-calendar-add").addEventListener("click", () => openEditor());
    q("#campus-calendar-day-add").addEventListener("click", () => openEditor());
    ["#campus-calendar-editor-close", "#campus-calendar-editor-cancel"].forEach(id => q(id).addEventListener("click", () => editor.close()));
    q("#campus-calendar-detail-close").addEventListener("click", () => detail.close());
    q("#campus-event-repeat").addEventListener("change", () => {
      q("#campus-event-until-label").hidden = q("#campus-event-repeat").value !== "weekly";
      q("#campus-event-until").required = q("#campus-event-repeat").value === "weekly";
      const weekly = q("#campus-event-repeat").value === "weekly";
      q('#campus-event-target option[value="google"]').disabled = weekly || !model.data?.google?.connected || !!model.editing;
      if (weekly) {
        q("#campus-event-target").value = "local";
        q("#campus-event-google-note").textContent = "Повторяющиеся занятия сохраняются в CampusPulse. Затем отдельное занятие можно отправить в Google из его карточки.";
      } else editorGoogleNote();
    });
    q("#campus-event-start").addEventListener("change", () => {
      const day = q("#campus-event-start").value.slice(0, 10);
      q("#campus-event-until").min = day;
      if (day && q("#campus-event-until").value < day) {
        const until = calendarDate(day); until.setUTCDate(until.getUTCDate() + 28);
        q("#campus-event-until").value = until.toISOString().slice(0, 10);
      }
    });
    q("#campus-calendar-form").addEventListener("submit", saveEvent);
    mounted = true;
    return true;
  }

  function render() {
    if (!mounted) return;
    const grid = q("#campus-calendar-grid");
    grid.replaceChildren();
    q("#campus-calendar").classList.toggle("is-week", model.view === "week");
    document.querySelectorAll("[data-calendar-view]").forEach(toggle => {
      toggle.classList.toggle("is-active", toggle.dataset.calendarView === model.view);
      toggle.setAttribute("aria-pressed", String(toggle.dataset.calendarView === model.view));
    });
    q("#campus-calendar-prev").setAttribute("aria-label", model.view === "week" ? "Предыдущая неделя" : "Предыдущий месяц");
    q("#campus-calendar-next").setAttribute("aria-label", model.view === "week" ? "Следующая неделя" : "Следующий месяц");
    const first = calendarDate(model.view === "week" ? model.day : `${model.month}-01`);
    const offset = (first.getUTCDay() + 6) % 7;
    const initial = new Date(first); initial.setUTCDate(first.getUTCDate() - offset);
    const last = new Date(initial); last.setUTCDate(last.getUTCDate() + 6);
    const short = value => new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" }).format(value);
    const weekMonth = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", timeZone: "UTC" }).formatToParts(last).find(part => part.type === "month").value;
    const monthLabel = model.view === "week" ? initial.getUTCMonth() === last.getUTCMonth() ? `${initial.getUTCDate()}–${last.getUTCDate()} ${weekMonth}` : `${short(initial)}–${short(last)}` : readableMonth(model.month);
    q("#campus-calendar-month").textContent = monthLabel;
    grid.setAttribute("aria-label", monthLabel);
    for (let i = 0; i < (model.view === "week" ? 7 : 42); i += 1) {
      const date = new Date(initial); date.setUTCDate(initial.getUTCDate() + i);
      const day = date.toISOString().slice(0, 10);
      const selected = day === model.day;
      const cell = make("div", `campus-day${day.startsWith(model.month) ? "" : " is-outside"}${day === today() ? " is-today" : ""}${selected ? " is-selected" : ""}`);
      cell.setAttribute("role", "gridcell"); cell.setAttribute("aria-selected", String(selected));
      const number = button(String(date.getUTCDate()), () => selectDay(day), "campus-day-number");
      number.setAttribute("aria-label", readableDay(day));
      if (day === today()) number.setAttribute("aria-current", "date");
      cell.append(number);
      const items = dayEvents(day);
      items.slice(0, 3).forEach(event => {
        const entry = button(event.title || "Без названия", () => showDetail(event), `campus-calendar-event kind-${eventKind(event)}${event.category === "important" ? " is-important" : ""}`);
        entry.title = `${event.title || "Событие"}, ${eventTime(event)}`;
        entry.setAttribute("aria-label", `${event.title || "Событие"}, ${eventTime(event)}, ${kinds[eventKind(event)]}`);
        cell.append(entry);
      });
      if (items.length > 3) cell.append(button(`ещё ${items.length - 3}`, () => selectDay(day), "campus-calendar-more"));
      grid.append(cell);
    }
    q("#campus-calendar-day").textContent = readableDay(model.day);
    const items = dayEvents(model.day);
    q("#campus-calendar-day-count").textContent = items.length ? `${items.length} ${items.length === 1 ? "событие" : items.length < 5 ? "события" : "событий"}` : "Время для твоих планов";
    const agenda = q("#campus-calendar-agenda"); agenda.replaceChildren();
    if (!items.length) {
      agenda.append(make("div", "campus-calendar-empty-mark", "✦"), make("p", "campus-calendar-empty", "На этот день пока ничего не запланировано."));
      if (!events().length) agenda.append(button("Посмотреть учебный пример", async () => {
        if (window.CampusAcademic?.changeDemo) {
          await window.CampusAcademic.changeDemo(false);
          if (typeof refresh === "function") await refresh();
          model.autoDay = true;
          await load(true);
        } else if (typeof showView === "function") showView("academic");
      }, "text-button campus-calendar-demo"));
    }
    let more = null;
    items.forEach((event, index) => {
      if (index === 3) {
        more = make("details", "campus-agenda-more");
        more.append(make("summary", "", `Ещё событий: ${items.length - 3}`));
        agenda.append(more);
      }
      const row = button("", () => showDetail(event), `campus-agenda-event kind-${eventKind(event)}`);
      const source = event.kind === "study" && (event.course || event.description) ? `${kinds[eventKind(event)]} · ${event.course || event.description}` : `${kinds[eventKind(event)]}${event.category ? ` · ${categories[event.category] || event.category}` : ""}`;
      row.append(make("span", "campus-agenda-time", eventTime(event)), make("strong", "", event.title || "Без названия"), make("small", "", source));
      (more || agenda).append(row);
    });
    const legend = q("#campus-calendar-legend"); legend.replaceChildren();
    Object.entries(kinds).forEach(([kind, label]) => legend.append(make("span", `kind-${kind}`, label)));
    const connected = model.data?.google?.connected;
    q("#campus-calendar-connection").textContent = connected ? "● Google подключён" : "● Календарь CampusPulse";
    q("#campus-calendar-connection").classList.toggle("is-connected", !!connected);
    q("#campus-calendar-zone").textContent = `Часовой пояс: ${timezone()}`;
    let coverage = q("#campus-calendar-coverage");
    if (!coverage) { coverage = make("p", "campus-calendar-coverage"); coverage.id = "campus-calendar-coverage"; q(".campus-calendar-footer").append(coverage); }
    coverage.textContent = model.data?.plan_coverage || "Учебная подготовка рассчитывается на ближайшие 14 дней.";
    q("#campus-calendar-export").href = `/api/calendar/export.ics?month=${encodeURIComponent(model.month)}`;
  }

  function openEditor(event = null) {
    if (!model.day) model.day = today();
    if (!model.month) model.month = model.day.slice(0, 7);
    q("#campus-calendar-detail")?.close();
    model.editing = event;
    model.autoDay = false;
    model.requestId = event ? null : [...crypto.getRandomValues(new Uint8Array(16))].map(value => value.toString(16).padStart(2, "0")).join("");
    const form = q("#campus-calendar-form"); form.reset();
    const start = event?.start ? inputDate(event.start) : `${model.day}T16:00`;
    const end = event?.end ? inputDate(event.end) : `${model.day}T17:00`;
    q("#campus-calendar-editor-title").textContent = event ? "Изменить событие" : "Новое событие";
    q("#campus-event-title").value = event?.title || "";
    q("#campus-event-start").value = start;
    q("#campus-event-end").value = end;
    q("#campus-event-description").value = event?.description || "";
    q("#campus-event-category").value = event?.category || "event";
    q("#campus-event-busy").checked = event?.busy !== false;
    q("#campus-event-repeat").value = "none";
    q("#campus-event-repeat").disabled = !!event;
    q("#campus-event-until-label").hidden = true;
    q("#campus-event-until").required = false;
    const until = calendarDate(model.day); until.setUTCDate(until.getUTCDate() + 28);
    q("#campus-event-until").value = until.toISOString().slice(0, 10);
    q("#campus-event-until").min = model.day;
    const googleOption = q('#campus-event-target option[value="google"]');
    googleOption.disabled = !model.data?.google?.connected || !!event;
    q("#campus-event-target").value = "local";
    q("#campus-event-target").disabled = !!event;
    q("#campus-event-zone").textContent = `Время в часовом поясе ${timezone()}`;
    editorGoogleNote();
    q("#campus-event-error").textContent = "";
    q("#campus-calendar-editor").showModal();
    q("#campus-event-title").focus();
  }

  function editorGoogleNote() {
    q("#campus-event-google-note").textContent = model.editing ? "Изменение относится к этому событию. Событие Google можно открыть по ссылке в его карточке." : model.data?.google?.connected ? "Выбери Google Calendar для прямого добавления в подключённый аккаунт." : "Событие сохранится в CampusPulse. Прямое добавление в Google станет доступно после подключения аккаунта ниже.";
  }

  async function refreshPlans() {
    if (typeof loadPlan === "function") await loadPlan();
    if (window.CampusAcademic?.load) window.CampusAcademic.load();
  }

  async function saveEvent(event) {
    event.preventDefault();
    const submit = q("#campus-event-submit");
    submit.disabled = true; q("#campus-event-error").textContent = "";
    let payload;
    const existingIds = new Set(events().map(item => item.id));
    try {
      const start = isoDate(q("#campus-event-start").value);
      const end = isoDate(q("#campus-event-end").value);
      if (new Date(end) <= new Date(start)) throw new Error("Окончание должно быть позже начала.");
      const weekly = q("#campus-event-repeat").value === "weekly";
      payload = { title: q("#campus-event-title").value.trim(), start, end, description: q("#campus-event-description").value.trim(), category: q("#campus-event-category").value, busy: q("#campus-event-busy").checked, repeat: weekly ? "weekly" : "none", repeat_until: weekly ? q("#campus-event-until").value : null, target: q("#campus-event-target").value };
      if (!model.editing) payload.request_id = model.requestId;
      if (!payload.title) throw new Error("Добавь название события.");
      const saved = await request(model.editing ? `/events/${encodeURIComponent(model.editing.id)}` : "/events", model.editing ? "PUT" : "POST", payload);
      model.day = dateKey(start); model.month = model.day.slice(0, 7);
      q("#campus-calendar-editor").close();
      await load(true);
      report(payload.target === "google" ? "Событие добавлено в подключённый Google Calendar." : saved?.occurrence_count > 1 ? `Сохранено событий: ${saved.occurrence_count}. Занятия учтутся в учебном плане.` : "Событие сохранено. Занятое время учтётся в учебном плане.");
      await refreshPlans();
    } catch (error) {
      // A Google network error may occur AFTER the local event was saved.
      // Recover that record so a retry uses its existing ID instead of POSTing
      // another event. Pending records deliberately cannot be edited/deleted.
      if (payload?.target === "google" && !model.editing) {
        model.day = dateKey(payload.start); model.month = model.day.slice(0, 7);
        await load(true);
        const saved = events().find(item => !existingIds.has(item.id) && item.title === payload.title && new Date(item.start).getTime() === new Date(payload.start).getTime() && new Date(item.end).getTime() === new Date(payload.end).getTime());
        if (saved) {
          q("#campus-calendar-editor").close(); showDetail(saved); report(error.message, true);
          return;
        }
      }
      q("#campus-event-error").textContent = error.message;
    }
    finally { submit.disabled = false; }
  }

  function showDetail(event) {
    q("#campus-calendar-detail-source").textContent = `${kinds[eventKind(event)]}${event.category ? ` · ${categories[event.category] || event.category}` : ""}`;
    q("#campus-calendar-detail-title").textContent = event.title || "Событие";
    const content = q("#campus-calendar-detail-content"); content.replaceChildren();
    content.append(make("p", "campus-detail-date", readableDay(dateKey(event.start))), make("p", "campus-detail-time", `${eventTime(event)} · ${timezone()}`));
    if (event.description) content.append(make("p", "campus-detail-description", event.description));
    content.append(make("p", "campus-calendar-form-note", event.busy === false ? "Свободное время: это событие не блокирует подготовку." : "Это время учитывается как занятое при планировании."));
    const actions = q("#campus-calendar-detail-actions"); actions.replaceChildren();
    const googleUrl = safeGoogleUrl(event.google_url || event.htmlLink || "");
    if (googleUrl) { const link = make("a", "button secondary", "В Google ↗"); link.href = googleUrl; link.target = "_blank"; link.rel = "noopener noreferrer"; actions.append(link); }
    const pending = event.google_status === "pending";
    const editable = event.kind === "local" && event.editable !== false && !["synced", "created", "pending"].includes(event.google_status);
    if (pending) content.append(make("p", "campus-calendar-form-note", "Добавление в Google пока не подтверждено. Повторная проверка использует то же событие и помогает избежать дубликатов."));
    if (editable) {
      actions.append(button("Изменить", () => openEditor(event)));
      actions.append(button("Удалить", async () => {
        const accepted = typeof confirmAction === "function" ? await confirmAction("Удалить событие?", "Оно исчезнет из календаря CampusPulse. Остальные события останутся.") : window.confirm("Удалить это событие?");
        if (!accepted) return;
        try { await request(`/events/${encodeURIComponent(event.id)}`, "DELETE"); q("#campus-calendar-detail").close(); await load(true); report("Событие удалено."); await refreshPlans(); }
        catch (error) { report(error.message, true); }
      }, "text-button campus-calendar-delete"));
    }
    if ((editable || pending) && model.data?.google?.connected) actions.append(button(pending ? "Проверить и повторить Google" : "Добавить в Google", async () => {
        try { await request(`/events/${encodeURIComponent(event.id)}/google`, "POST", {}); q("#campus-calendar-detail").close(); await load(true); report("Событие добавлено в Google Calendar."); }
        catch (error) { report(error.message, true); }
      }));
    if (!editable && !pending && !googleUrl) content.append(make("p", "campus-calendar-form-note", event.kind === "study" ? "Учебный план обновляется автоматически после изменения оценок и доступного времени." : event.kind === "deadline" ? "Этот срок берётся из задания или оценочной работы. Измени его в исходной карточке." : event.kind === "imported" ? "Это событие из загруженного расписания. Обнови расписание, чтобы изменить его." : "Для изменения события открой Google Calendar."));
    q("#campus-calendar-detail").showModal();
  }

  async function load(force = false) {
    if (!mount()) return;
    if (!model.day) model.day = today();
    if (!model.month) model.month = model.day.slice(0, 7);
    if (!force && model.request && model.loadKey === model.month) return model.request;
    if (!force && model.loadKey === model.month && Date.now() - model.loadedAt < 2000) return;
    const token = ++model.token;
    model.loadKey = model.month;
    report("Обновляю календарь…");
    q("#campus-calendar").setAttribute("aria-busy", "true");
    render();
    model.request = (async () => {
      try {
        const data = await request(`/dashboard?month=${encodeURIComponent(model.month)}`);
        if (token !== model.token) return;
        model.data = data; model.loadedAt = Date.now();
        if (model.autoDay && !dayEvents(model.day).length) {
          const next = events().filter(item => new Date(item.start) >= new Date() && new Date(item.start) - new Date() <= 7 * 86400000).sort((a, b) => new Date(a.start) - new Date(b.start))[0];
          if (next) { model.day = dateKey(next.start); model.month = model.day.slice(0, 7); }
        }
        model.autoDay = false;
        render();
        report((data.warnings || []).filter(item => typeof item === "string").join(" "));
      } catch (error) { if (token === model.token) report(error.message, true); }
      finally { if (token === model.token) { model.request = null; q("#campus-calendar").setAttribute("aria-busy", "false"); } }
    })();
    return model.request;
  }
  window.CampusCalendar = { load, newEvent: () => { mount(); openEditor(); } };
  const initialize = () => {
    if (!mount()) return;
    new MutationObserver(() => { if (!q("#view-week").hidden) load(); }).observe(q("#view-week"), { attributes: true, attributeFilter: ["hidden"] });
    if (!q("#view-week").hidden || location.hash === "#week") load();
    ["calendar-sync", "calendar-disconnect"].forEach(id => q(`#${id}`)?.addEventListener("click", () => setTimeout(() => { if (!q("#view-week").hidden) load(true); }, 800)));
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize); else initialize();
})();
