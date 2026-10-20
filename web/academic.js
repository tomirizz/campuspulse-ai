"use strict";

/* Every number shown here comes from the academic APIs. No grades are invented. */
(() => {
  const q = (selector, parent = document) => parent.querySelector(selector);
  const all = (selector, parent = document) => [...parent.querySelectorAll(selector)];
  const academic = { courses: [], summary: {}, settings: {}, plan: null, editing: null, importKind: "syllabus", selectedTarget: null, detailId: null, pending: null };
  const colors = ["#9a7bd3", "#daaa92", "#96b5aa", "#b8a0d8", "#d9bf7d", "#8ea8cf", "#cf9cba"];
  const riskLabels = { critical: "Нужна поддержка", high: "В зоне внимания", medium: "Держим в фокусе", low: "Хороший темп", ungraded: "Ждём первые оценки", complete: "Предмет завершён" };
  const n = (value, decimals = 1) => Number.isFinite(Number(value)) ? Number(value).toLocaleString("ru-RU", { maximumFractionDigits: decimals }) : "—";
  const pct = (value) => value === null || value === undefined ? "—" : `${n(value)}%`;
  const neededPct = (value) => value === null || value === undefined ? "—" : `${n(Math.ceil(Number(value) * 10 - 1e-9) / 10)}%`;
  const maximumScore = (component) => Number(component.max_score || 100);
  const neededScore = (item, conditional = false) => {
    const maximum = maximumScore(item);
    const score = conditional ? item.conditional_min_score : item.required_score;
    return maximum === 100 ? neededPct(conditional ? item.conditional_min_percent : item.required_percent)
      : score == null ? "—" : `${n(score, 6)} из ${n(maximum, 6)}`;
  };
  const minutes = (value) => {
    const m = Math.max(0, Math.round(Number(value) || 0));
    return m >= 60 ? `${Math.floor(m / 60)} ч${m % 60 ? ` ${m % 60} мин` : ""}` : `${m} мин`;
  };
  const node = (tag, className, text) => {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined && text !== null) result.textContent = String(text);
    return result;
  };
  const action = (text, callback, className = "button secondary") => {
    const result = node("button", className, text);
    result.type = "button";
    result.addEventListener("click", callback);
    return result;
  };
  const writeStatus = (text = "", error = false) => {
    q("#academic-status").textContent = text;
    q("#academic-status").classList.toggle("is-error", error);
  };
  const notify = (text, error = false) => typeof toast === "function" ? toast(text, error) : writeStatus(text, error);
  const request = async (path, method = "GET", body) => {
    const options = { method };
    if (body instanceof FormData) options.body = body;
    else if (body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(`/api/academic${path}`, options);
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch (_) { /* response may not be JSON */ }
      throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? "Проверь значения и обязательные поля формы." : `Не удалось выполнить запрос (${response.status}).`);
    }
    return response.status === 204 ? null : response.json();
  };
  const safeDate = (value, options = {}) => {
    if (!value || !Number.isFinite(new Date(value).getTime())) return "Без даты";
    return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: academic.settings.timezone || "Asia/Almaty", ...options }).format(new Date(value));
  };
  const clockLabel = (value) => safeDate(value, { day: undefined, month: undefined, hour: "2-digit", minute: "2-digit" });
  const localInput = (value, timezone = academic.settings.timezone || "Asia/Almaty") => {
    if (!value) return "";
    if (typeof wallTime === "function") return wallTime(value, timezone);
    return String(value).slice(0, 16);
  };
  const isoInput = (value, timezone = academic.settings.timezone || "Asia/Almaty") => {
    if (!value) return null;
    if (typeof isoFromWall === "function") return isoFromWall(value, timezone);
    return new Date(value).toISOString();
  };
  const findCourse = (id) => academic.courses.find((course) => String(course.id) === String(id));
  const riskClass = (course) => ["high", "critical"].includes(course.risk) ? " is-risk" : "";
  const manualDifficulty = (course) => course?.difficulty_source === "manual" || course?.difficulty_source === "user" || course?.difficulty_source === "Ваша оценка сложности";

  async function load() {
    if (academic.pending) return academic.pending;
    academic.pending = (async () => {
      writeStatus("Обновляем оценки и свободные окна…");
      try {
        const [data, plan] = await Promise.all([request(""), request("/plan")]);
        academic.courses = data.courses || [];
        academic.drafts = data.drafts || [];
        academic.summary = data.summary || {};
        academic.settings = data.settings || {};
        academic.importedSchedule = data.imported_schedule || [];
        academic.scheduleNotes = data.schedule_notes || [];
        academic.demo = data.demo || {active:false};
        renderDemoControls();
        academic.plan = plan;
        renderOverview();
        renderCourses();
        renderPlan();
        renderAcademicProgress();
        writeStatus();
      } catch (error) {
        writeStatus(error.message, true);
        if (!q("#academic-overview").children.length) renderOverview();
        if (!q("#academic-courses").children.length) renderCourses();
      } finally { academic.pending = null; }
    })();
    return academic.pending;
  }

  async function reloadAfterChange() {
    if (academic.pending) await academic.pending;
    return load();
  }

  async function startStudy(course, session) {
    const options = { course_id:course?.id || null, material_ids: course?.material_ids || [], course: course?.name || session?.course || "", focus: session?.title || "" };
    if (window.CampusNotebook?.prepare) await window.CampusNotebook.prepare(options);
    else showView("notebook");
  }

  async function changeDemo(remove = false) {
    if (academic.demoPending) return false;
    academic.demoPending = true;
    renderDemoControls();
    try {
      writeStatus(remove ? "Убираем учебный пример…" : "Добавляем учебный пример…");
      await request("/demo", remove ? "DELETE" : "POST", remove ? undefined : {});
      academic.selectedDay = null;
      await reloadAfterChange();
      await refresh();
      notify(remove ? "Пример убран. Твои данные сохранены." : "Готово. Это учебные данные — их можно убрать одной кнопкой.");
      return true;
    } catch (error) { writeStatus(error.message, true); notify(error.message, true); return false; }
    finally { academic.demoPending = false; renderDemoControls(); }
  }

  function renderDemoControls() {
    const active = !!academic.demo?.active;
    q("#add-demo").textContent = active ? "Открыть учебный пример ↗" : "Добавить учебный пример";
    q("#add-demo").disabled = !!academic.demoPending;
    q("#remove-demo").hidden = !active;
    q("#remove-demo").disabled = !!academic.demoPending;
  }

  async function loadDemoStatus() {
    try { academic.demo = (await request("")).demo || {active:false}; renderDemoControls(); }
    catch (error) { notify(error.message, true); }
  }

  function renderOverview() {
    const hasCourses = academic.courses.length > 0 || (academic.drafts || []).length > 0;
    q(".academic-header-actions").hidden = !hasCourses;
    q("#academic-courses-heading").hidden = !hasCourses;
    q("#academic-plan-section").hidden = !hasCourses;
    const banner = q("#academic-demo-banner");
    banner.replaceChildren();
    if (academic.demo?.active) {
      const row = node("div", "academic-demo-notice");
      row.append(node("span", "", "Учебный пример · " + (academic.demo.course_ids?.length || academic.demo.count || 4) + " предмета"), action("Убрать пример ×", () => changeDemo(true), "text-button"));
      banner.append(row);
    }
    const area = q("#academic-overview");
    area.replaceChildren();
    if (!academic.courses.length) {
      const start = node("article", "academic-start");
      start.append(node("span", "academic-start-mark", "↗"), node("h2", "", academic.drafts?.length ? "Предметы добавлены. Теперь — силлабус" : "Начни с предмета и расписания"), node("p", "", academic.drafts?.length ? "Расписание уже учитывается. Загрузи силлабус к любому предмету ниже — тогда появятся формула оценки и нужные баллы." : "Вставь текст силлабуса и расписания или выбери файлы. Мы найдём работы и их вес, покажем нужные баллы и время для подготовки."));
      const buttons = node("div", "academic-actions");
      buttons.append(action("Добавить предмет и расписание", () => openImport("combined"), "button primary"), action("Посмотреть пример", () => changeDemo(), "button secondary"));
      start.append(buttons, node("small", "academic-start-hint", "PDF, фото или текст. Настраивать всё вручную не нужно."));
      const steps = node("div", "academic-start-steps");
      for (const [number, title, text] of [["1", "Добавь силлабус", "Мы найдём задания и их вес."], ["2", "Внеси оценки", "Покажем, сколько осталось до цели."], ["3", "Начни подготовку", "Время и материалы уже под рукой."]]) {
        const step = action("", () => {
          if (number === "1") openImport("combined");
          else if (academic.courses.length) number === "2" ? openDetail(academic.courses[0].id) : startStudy(academic.courses[0]);
          else { notify(number === "2" ? "Сначала добавь предмет — затем можно будет внести оценки." : "Сначала добавь предмет или открой учебный пример."); openImport("combined"); }
        }, "academic-start-step");
        step.append(node("span", "", number), node("strong", "", title), node("p", "", text));
        steps.append(step);
      }
      start.append(steps, action("Добавить предмет вручную", () => openEditor(), "text-button academic-manual-link"));
      area.append(start);
      return;
    }
    const sessions = [...(academic.plan?.sessions || [])].filter((item) => new Date(item.end) > new Date()).sort((a, b) => new Date(a.start) - new Date(b.start));
    const session = sessions[0];
    const course = session ? academic.courses.find((item) => session.course_id ? item.id === session.course_id : item.name === session.course) || {name:session.course || session.title,material_ids:[]} : [...academic.courses].sort((a, b) => b.priority_score - a.priority_score)[0];
    const next = node("article", "academic-next-step");
    const copy = node("div");
    const today = localInput(new Date().toISOString()).slice(0, 10);
    const nextToday = session && localInput(session.start).startsWith(today);
    copy.append(node("div", "eyebrow", nextToday ? "СЛЕДУЮЩИЙ ШАГ СЕГОДНЯ" : "СЛЕДУЮЩИЙ ШАГ"), node("h2", "", course.name));
    const topic = session?.title && session.title !== course.name ? session.title : "Повтори главное из материалов";
    copy.append(node("p", "", topic), node("div", "academic-next-tags", (session ? safeDate(session.start) + " · " + clockLabel(session.start) + " · " + minutes(session.minutes) : "Начни с короткого повторения") + (course.active_target == null ? "" : " · цель " + n(course.active_target))));
    next.append(copy, action("Готовиться →", () => startStudy(course, session), "button primary"));
    area.append(next);
    const strip = node("div", "academic-summary-strip");
    for (const [label, value] of [["Текущий GPA", academic.summary.current_gpa == null ? "—" : n(academic.summary.current_gpa, 2)], ["Цель по умолчанию", n(academic.settings.preferred_target ?? 95)], ["Нужно внимания", n(academic.summary.at_risk || 0, 0)]]) {
      const metric = node("div");
      metric.append(node("span", "", label), node("strong", "", value));
      strip.append(metric);
    }
    area.append(strip);
  }

  function renderCourses() {
    q("#academic-course-count").textContent = academic.courses.length + (academic.drafts || []).length;
    const area = q("#academic-courses");
    area.replaceChildren();
    const courses = [...academic.courses].sort((a, b) => Number(b.priority_score || 0) - Number(a.priority_score || 0));
    for (const course of courses) {
      const card = node("article", "academic-course" + riskClass(course));
      const top = node("div", "academic-course-top");
      const title = node("div");
      title.append(node("h3", "", course.name));
      const edit = action("⋯", () => openEditor(course), "academic-course-menu");
      edit.setAttribute("aria-label", "Редактировать " + course.name);
      top.append(title, edit);
      card.append(top);
      const numbers = node("div", "academic-simple-score");
      const current = node("div");
      current.append(node("strong", "", course.current_average == null ? "—" : n(course.current_average) + "%"), node("span", "", "сейчас · по сданному"));
      const goal = node("div", "academic-simple-goal");
      goal.append(node("strong", "", course.active_target == null ? "—" : n(course.active_target) + "%"), node("span", "", "цель"));
      numbers.append(current, goal);
      card.append(numbers);
      const progress = node("div", "academic-goal-progress");
      const fill = node("span");
      fill.style.width = Math.max(0, Math.min(100, Number(course.current_average) || 0)) + "%";
      const mark = node("i");
      mark.style.left = Math.max(0, Math.min(100, Number(course.active_target ?? course.target) || 0)) + "%";
      progress.append(fill, mark);
      progress.setAttribute("role", "img");
      progress.setAttribute("aria-label", "Текущая оценка за сданные задания: " + pct(course.current_average) + ". Цель: " + n(course.active_target ?? course.target) + " процентов.");
      card.append(progress);
      const scenario = (course.scenarios || []).find((item) => Number(item.target) === Number(course.active_target));
      let requirement;
      if (Number(course.remaining_weight) <= 0) requirement = "Все оценки внесены · итог " + n(course.earned_points) + " из 100";
      else if (course.current_average == null) requirement = "Добавь первую оценку — рассчитаем следующий шаг.";
      else if (scenario?.required_average != null) requirement = "На оставшихся работах нужно в среднем " + neededPct(scenario.required_average);
      else requirement = "Лучший доступный итог — " + pct(course.max_achievable);
      card.append(node("p", "academic-course-requirement", requirement));
      if (course.policy_warnings?.length) card.append(action("Дополнительные условия сдачи ⚠", () => {
        const copy = node("div");
        course.policy_warnings.forEach((warning) => copy.append(node("p", "", warning)));
        copy.append(node("p", "", "Эти условия сохранены из силлабуса, но не применяются автоматически к формуле баллов. Проверь их отдельно."));
        showExplanation("Условия из силлабуса", copy);
      }, "text-button academic-policy-warning"));
      if (course.target_lowered) card.append(node("small", "academic-goal-adjusted", "Цель " + n(course.active_target ?? course.max_achievable) + " уже учитывает твои оценки."));
      const footer = node("div", "academic-course-footer");
      footer.append(action("Внести оценки →", () => openDetail(course.id), "text-button"), action("Готовиться", () => startStudy(course), "academic-study-link"));
      card.append(footer);
      area.append(card);
    }
    renderDrafts();
  }

  function renderAcademicProgress() {
    const area = q("#academic-progress-card");
    const progress = state.progress;
    area.hidden = !progress || (!academic.courses.length && !progress.xp && !progress.completed);
    if (area.hidden) return;
    area.replaceChildren();
    const orbit = node("div", "academic-progress-orbit");
    orbit.setAttribute("aria-hidden", "true");
    orbit.append(node("span", "academic-progress-ring"));
    const planet = node("div", "academic-mini-planet");
    const eyes = node("span", "academic-mini-eyes");
    eyes.append(node("i"), node("i"));
    planet.append(eyes, node("span", "academic-mini-smile"));
    orbit.append(planet, node("span", "academic-progress-star star-a", "✦"), node("span", "academic-progress-star star-b", "✧"));
    const copy = node("div", "academic-progress-copy");
    copy.append(node("div", "academic-progress-eyebrow", "ТВОЙ ПРОГРЕСС"), node("h2", "", progress.xp ? "Маленькие шаги. Настоящее движение." : "Большой путь начинается с одного шага."));
    const numbers = node("div", "academic-progress-numbers");
    numbers.append(node("strong", "", n(progress.xp, 0) + " XP"), node("span", "", "Уровень " + n(progress.level, 0)), node("small", "", "До следующего: " + n(progress.next_level_xp, 0) + " XP"));
    copy.append(numbers);
    const bar = node("progress");
    bar.max = 100;
    bar.value = Number(progress.level_progress) || 0;
    bar.setAttribute("aria-label", "Прогресс до следующего уровня: " + n(progress.level_progress, 0) + " из 100 XP");
    copy.append(bar);
    const facts = progress.why?.xp?.inputs?.["квесты"]?.length || 0;
    const completed = Number(progress.completed) || 0;
    const caption = completed || facts
      ? "Завершено: " + completed + " " + plural(completed, ["задание", "задания", "заданий"]) + " · Освоено: " + facts + " " + plural(facts, ["факт", "факта", "фактов"])
      : "Опыт появится за выполненные задания и освоенные факты в тренировке.";
    copy.append(node("p", "academic-progress-caption", caption));
    const actions = node("div", "academic-progress-actions");
    actions.append(action("Мой путь ↗", () => showView("journey"), "button secondary"), action("За что начислен опыт?", () => showWhy(progress.why.xp), "academic-progress-why"));
    area.append(orbit, copy, actions);
  }

  function renderPlan() {
    const area = q("#academic-plan");
    area.replaceChildren();
    const plan = academic.plan;
    if (!plan || !academic.courses.length) return;
    const days = plan.days || [];
    const today = localInput(new Date().toISOString()).slice(0, 10);
    if (!days.some((day) => String(day.date).slice(0, 10) === academic.selectedDay)) academic.selectedDay = String((days.find((day) => String(day.date).slice(0, 10) === today && day.sessions?.length) || days.find((day) => day.sessions?.length) || days[0])?.date || today).slice(0, 10);
    const dates = node("div", "academic-date-strip");
    for (const [index, day] of days.entries()) {
      const key = String(day.date).slice(0, 10);
      const date = new Date(key + "T12:00:00Z");
      const selected = key === academic.selectedDay;
      const tab = action("", () => { academic.selectedDay = key; academic.showAllSessions = false; renderPlan(); }, "academic-date-tab" + (selected ? " is-selected" : ""));
      tab.setAttribute("aria-pressed", String(selected));
      const label = key === today ? "Сегодня" : index === 1 && String(days[0]?.date).slice(0, 10) === today ? "Завтра" : new Intl.DateTimeFormat("ru-RU", {weekday:"short", timeZone:"UTC"}).format(date);
      tab.append(node("span", "", label), node("strong", "", new Intl.DateTimeFormat("ru-RU", {day:"numeric", timeZone:"UTC"}).format(date)), node("i", day.sessions?.length ? "has-plan" : ""));
      dates.append(tab);
    }
    area.append(dates);
    const day = days.find((item) => String(item.date).slice(0, 10) === academic.selectedDay);
    const sessions = day?.sessions || [];
    const list = node("div", "academic-agenda");
    const visible = academic.showAllSessions ? sessions : sessions.slice(0, 3);
    for (const session of visible) {
      const row = node("article", "academic-agenda-row");
      const time = node("div", "academic-agenda-time");
      time.append(node("strong", "", clockLabel(session.start)), node("small", "", minutes(session.minutes)));
      const copy = node("div", "academic-agenda-copy");
      copy.append(node("strong", "", session.course || session.title), node("span", "", session.title === session.course ? "Повторение материала" : session.title || "Подготовка"));
      const course = academic.courses.find((item) => session.course_id ? item.id === session.course_id : item.name === session.course);
      row.append(time, copy, action("Начать →", () => startStudy(course, session), "text-button"));
      list.append(row);
    }
    if (!sessions.length) list.append(node("p", "academic-agenda-empty", "На этот день подготовки нет. Можно отдохнуть или повторить материал."));
    area.append(list);
    const controls = node("div", "academic-agenda-controls");
    if (sessions.length > 3) controls.append(action(academic.showAllSessions ? "Свернуть" : "Ещё занятия (" + (sessions.length - 3) + ")", () => { academic.showAllSessions = !academic.showAllSessions; renderPlan(); }, "text-button"));
    controls.append(action("Показать весь план ↗", () => showView("week"), "text-button"));
    area.append(controls);
    const allocations = plan.course_allocations || [];
    const total = allocations.reduce((sum, item) => sum + Number(item.scheduled_minutes ?? item.minutes ?? 0), 0);
    if (total > 0) {
      const details = node("details", "academic-allocation-details");
      details.append(node("summary", "", "Как распределено время на неделю · " + minutes(total)));
      const strip = node("div", "academic-allocation");
      const key = node("div", "academic-allocation-key");
      allocations.forEach((item, index) => {
        const amount = Number(item.scheduled_minutes ?? item.minutes ?? 0);
        if (!amount) return;
        const slice = node("span");
        slice.style.width = amount / total * 100 + "%";
        slice.style.backgroundColor = colors[index % colors.length];
        strip.append(slice);
        const legend = node("span");
        const dot = node("i");
        dot.style.backgroundColor = colors[index % colors.length];
        legend.append(dot, document.createTextNode(item.course + " · " + minutes(amount)));
        key.append(legend);
      });
      details.append(strip, key);
      area.append(details);
    }
    const notes = node("details", "academic-details-source");
    notes.append(node("summary", "", "Подробнее о плане" + (plan.risks?.length ? " · есть ограничения" : "")), node("p", "", "Учитываем оценки, дедлайны, сложность и кредиты. По умолчанию — 3 часа в день. Занятые часы из расписания исключаются."));
    for (const risk of (plan.risks || []).slice(0, 8)) notes.append(node("p", "", (risk.course || risk.title || "План") + ": " + risk.reason));
    for (const text of plan.schedule_notes || academic.scheduleNotes || []) notes.append(node("p", "", text));
    area.append(notes);
  }

  function showDialog(id) {
    const dialog = q(id);
    if (!dialog.open) dialog.showModal();
  }

  function errorAt(selector, error) {
    q(selector).textContent = error ? error.message || String(error) : "";
    q(selector).hidden = !error;
  }

  function renderDrafts() {
    const area = q("#academic-courses");
    for (const draft of academic.drafts || []) {
      const card = node("article", "academic-course academic-draft-course");
      card.append(node("span", "academic-draft-badge", "Из расписания · без силлабуса"), node("h3", "", draft.name), node("p", "academic-form-help", "Занятия уже учтены в свободном времени. Добавь оценивание — рассчитаем цель и нужные баллы без ручной настройки формулы."));
      card.append(action("Добавить силлабус →", () => openImport("syllabus", draft), "button primary"), action("Убрать предмет", async () => {
        if (!(await confirmAction("Убрать этот предмет?", "Удалится только черновик предмета. Расписание и материалы сохранятся."))) return;
        try { await request(`/course-drafts/${encodeURIComponent(draft.id)}`, "DELETE"); await reloadAfterChange(); }
        catch (error) { notify(error.message, true); }
      }, "text-button"));
      area.append(card);
    }
  }

  function componentRow(component = {}) {
    const row = node("div", "academic-component-row");
    row._component = { ...component };
    const input = (key, type, value, label) => {
      const element = node("input");
      element.dataset.field = key;
      element.type = type;
      element.value = value ?? "";
      element.setAttribute("aria-label", label);
      return element;
    };
    const name = input("name", "text", component.name, "Название задания");
    name.maxLength = 160;
    name.required = true;
    name.placeholder = "Название задания";
    const weight = input("weight", "number", component.weight, "Вес в итоговой оценке, процентов");
    weight.min = "0.01";
    weight.max = "100";
    weight.step = "0.01";
    weight.required = true;
    weight.addEventListener("input", updateWeightTotal);
    const maximum = maximumScore(component);
    const score = input("score", "number", component.score == null ? "" : component.score, "Полученные баллы. Пусто, если не сдано.");
    score.min = "0";
    score.max = String(maximum);
    score.step = "0.01";
    score.placeholder = "—";
    const max = input("max_score", "number", maximum, "Максимум баллов за задание");
    max.min = "0.01"; max.max = "100000"; max.step = "0.01"; max.required = true;
    max.addEventListener("input", () => { score.max = max.value; });
    const scoreFields = node("div", "academic-component-score");
    const separator = node("span", "", "/"); separator.setAttribute("aria-hidden", "true");
    scoreFields.append(score, separator, max);
    const date = input("due_at", "datetime-local", localInput(component.due_at), "Дедлайн задания, необязательно");
    const remove = action("×", () => { row.remove(); updateWeightTotal(); }, "academic-remove-component");
    remove.setAttribute("aria-label", "Убрать задание из формулы");
    row.append(name, weight, scoreFields, date, remove);
    if (component.source_quote) {
      const quote = node("details", "academic-component-quote");
      quote.append(node("summary", "", "Из силлабуса"), node("p", "", component.source_quote));
      row.append(quote);
    }
    q("#academic-components").append(row);
    updateWeightTotal();
  }

  function updateWeightTotal() {
    const total = all('[data-field="weight"]', q("#academic-components")).reduce((sum, input) => sum + (Number(input.value) || 0), 0);
    const valid = Math.abs(total - 100) < .01;
    q("#academic-weight-total").textContent = `Общий вес: ${n(total, 2)} / 100%${valid ? " ✓" : " · проверь веса"}`;
    q("#academic-weight-total").classList.toggle("is-invalid", !valid);
  }

  function openEditor(course = null, source = null) {
    academic.editing = course?.id || null;
    academic.editorSchedule = source?._schedule || null;
    academic.editorDraftId = source?._draft_id || null;
    academic.editorDraftName = source?._draft_name || null;
    academic.editorPolicyWarnings = [...(source?.policy_warnings || course?.policy_warnings || [])];
    academic.editorDraftChoice = null;
    academic.editorMaterialIds = [...(course?.material_ids || [])];
    q("#academic-editor-title").textContent = course?.id ? "Редактировать предмет" : source ? "Проверь распознанный силлабус" : "Новый предмет";
    q("#academic-course-form").reset();
    q("#academic-name").value = course?.name || "";
    q("#academic-credits").value = source && course?.credits == null ? "" : course?.credits ?? 5;
    q("#academic-term").value = course?.term || "trimester";
    q("#academic-target").value = course?.target ?? academic.settings.preferred_target ?? 95;
    q("#academic-difficulty").value = manualDifficulty(course) ? course.difficulty : "";
    q("#academic-components").replaceChildren();
    q("#academic-source-notice").replaceChildren();
    if (source) {
      const notice = node("div", "academic-source-notice");
      notice.append(node("p", "", "Проверь название и веса, затем сохрани предмет."));
      for (const warning of source.warnings || []) notice.append(node("p", "", `• ${warning}`));
      if (academic.editorSchedule) {
        const schedule = academic.editorSchedule;
        notice.append(node("p", "", schedule.recurring ? `Также сохраним расписание: ${schedule.weekly_rules?.length || "—"} занятий в неделю, ${schedule.weeks} недель. Период: ${String(schedule.week_start || "").slice(0, 10)} — ${String(schedule.coverage_end || "").slice(0, 10)}.` : `Также сохраним расписание: ${(schedule.busy || []).length} событий.`));
        const preview = node("details");
        preview.append(node("summary", "", "Посмотреть расписание перед сохранением"));
        (schedule.busy || []).slice(0, schedule.weekly_rules?.length || 30).forEach((item) => preview.append(node("p", "", `${safeDate(item.start)} · ${clockLabel(item.start)}–${clockLabel(item.end)} · ${item.title}`)));
        notice.append(preview);
        academic.editorDraftChoice = appendDraftChoice(notice, schedule);
      }
      q("#academic-source-notice").append(notice);
    }
    const components = course?.components?.length ? course.components : [{ name: "Assignment 1", weight: 20 }, { name: "Midterm", weight: 30 }, { name: "Final exam", weight: 50 }];
    components.forEach(componentRow);
    errorAt("#academic-editor-error", null);
    q("#academic-course-save").textContent = academic.editorSchedule ? "Сохранить предмет и расписание" : "Сохранить предмет";
    showDialog("#academic-course-dialog");
  }

  function collectEditor() {
    const components = all(".academic-component-row", q("#academic-components")).map((row) => {
      const value = (field) => q(`[data-field="${field}"]`, row).value;
      return {
        ...(row._component.id ? { id: row._component.id } : {}),
        name: value("name").trim(), weight: Number(value("weight")), score: value("score") === "" ? null : Number(value("score")),
        max_score: Number(value("max_score")), due_at: row._component.schedule_derived && value("due_at") === localInput(row._component.due_at) ? null : isoInput(value("due_at")), estimated_minutes: row._component.estimated_minutes || 120,
        source_quote: row._component.source_quote || null,
      };
    });
    if (!components.length) throw new Error("Добавь хотя бы одно задание или экзамен.");
    if (Math.abs(components.reduce((sum, item) => sum + item.weight, 0) - 100) >= .01) throw new Error("Сумма итоговых весов должна составлять ровно 100%. Исправь веса перед сохранением.");
    if (components.some((item) => !item.name || item.weight <= 0 || item.weight > 100 || !Number.isFinite(item.max_score) || item.max_score <= 0 || item.max_score > 100000 || item.score != null && (item.score < 0 || item.score > item.max_score))) throw new Error("Проверь название, вес, баллы и максимум каждого задания.");
    return { name: q("#academic-name").value.trim(), credits: Number(q("#academic-credits").value), difficulty: q("#academic-difficulty").value ? Number(q("#academic-difficulty").value) : null, target: Number(q("#academic-target").value), term: q("#academic-term").value, material_ids:academic.editorMaterialIds || [], policy_warnings:academic.editorPolicyWarnings || [], components };
  }

  q("#academic-course-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = q("#academic-course-save");
    if (save.disabled) return;
    try {
      const body = collectEditor();
      save.disabled = true;
      save.textContent = "Сохраняем предмет…";
      event.target.setAttribute("aria-busy", "true");
      const saved = await request(academic.editing ? `/courses/${encodeURIComponent(academic.editing)}` : "/courses", academic.editing ? "PUT" : "POST", body);
      academic.editing = saved.id;
      if (academic.editorSchedule) {
        try {
          await request("/schedule", "POST", schedulePayload(academic.editorSchedule));
          const names = academic.editorDraftChoice?.() || [];
          if (names.length) await request("/course-drafts", "POST", {names});
        }
        catch (error) { throw new Error("Предмет уже сохранён, но расписание пока не сохранилось: " + error.message + " Повтори сохранение — предмет не продублируется."); }
      }
      if (academic.editorDraftId && body.name.trim().toLocaleLowerCase() === academic.editorDraftName?.trim().toLocaleLowerCase()) {
        await request(`/course-drafts/${encodeURIComponent(academic.editorDraftId)}`, "DELETE");
        academic.editorDraftId = null;
      }
      q("#academic-course-dialog").close();
      await reloadAfterChange();
      notify(academic.editorSchedule ? "Предмет и расписание сохранены. План учитывает занятые часы." : "Предмет сохранён. Оценки и план пересчитаны.");
    } catch (error) { errorAt("#academic-editor-error", error); }
    finally { save.disabled = false; save.textContent = academic.editorSchedule ? "Сохранить предмет и расписание" : "Сохранить предмет"; event.target.setAttribute("aria-busy", "false"); }
  });

  function explainGrades() {
    const content = node("div");
    content.append(node("p", "", "Итог = сумма (оценка / максимум × вес). Например, 75 и 80 за два задания по 10% дают 15,5 балла из итоговых 100. Оставшийся вес — 80%, а максимально достижимый итог — 95,5."), node("p", "", "Для цели 95 нужно ещё 79,5 балла: 99,375% на оставшемся весе. Сбалансированный план распределяет одинаковый процент выполнения на каждое оставшееся задание. Это понятный план, но не единственная возможная комбинация оценок."), node("p", "", "Если 95 уже недостижимо, система проверяет 90, 85, 80, 75 и 70. Текущая оценка учитывает только уже оценённый вес; баллы в зачёте показывают вклад в полный итог."), node("p", "", "GPA считается по настраиваемой шкале и взвешивается по кредитам предметов. Это ориентир, а не официальный расчёт университета. Название Scholarship saver — мотивационная метка и не подтверждает право на стипендию."));
    showExplanation("Прозрачная формула. Достижимая цель.", content);
  }

  function showExplanation(title, content) {
    q("#why-title").textContent = title;
    q("#why-content").replaceChildren(content);
    showDialog("#why-dialog");
  }

  function openDetail(id, selectedTarget = null) {
    const course = findCourse(id);
    if (!course) return;
    academic.detailId = id;
    academic.selectedTarget = selectedTarget ?? course.active_target ?? course.target;
    q("#academic-detail-title").textContent = course.name;
    const area = q("#academic-detail-content");
    area.replaceChildren();
    const metrics = node("div", "academic-detail-metrics");
    const metric = (value, label) => {
      const box = node("div", "academic-detail-metric");
      box.append(node("strong", "", value), node("span", "", label));
      return box;
    };
    metrics.append(metric(pct(course.current_average), "Текущая оценка за сданное"), metric(n(course.earned_points), "Уже в зачёте из 100"), metric(pct(course.max_achievable), "Максимальный итог"));
    area.append(metrics);
    if (course.target_lowered) area.append(node("p", "academic-source-notice", `Цель ${n(course.target)} уже недостижима. ${course.active_target == null ? "Посмотрим, как получить лучший доступный результат." : `Рабочая цель — ${n(course.active_target)}.`}`));
    const targetSelector = node("details", "academic-target-selector");
    targetSelector.append(node("summary", "", `Цель ${n(academic.selectedTarget)} · посмотреть другие цели`));
    const targetButtons = node("div", "academic-targets");
    for (const scenario of course.scenarios || []) {
      const target = action("", () => openDetail(id, scenario.target), "academic-target" + (Number(academic.selectedTarget) === Number(scenario.target) ? " is-selected" : "") + (!scenario.feasible ? " is-impossible" : ""));
      target.setAttribute("aria-pressed", String(Number(academic.selectedTarget) === Number(scenario.target)));
      target.append(node("strong", "", n(scenario.target)), node("small", "", scenario.label || ""), node("small", "", `GPA ${n(scenario.gpa, 2)}`));
      target.title = scenario.feasible ? "Посмотреть план на эту цель" : "Посмотреть, почему цель недостижима";
      targetButtons.append(target);
    }
    targetSelector.append(targetButtons);
    area.append(targetSelector);
    const scenario = (course.scenarios || []).find((item) => Number(item.target) === Number(academic.selectedTarget));
    const calculation = node("div", "academic-calculation" + (scenario && !scenario.feasible ? " is-impossible" : ""));
    if (Number(course.remaining_weight) <= 0) {
      calculation.append(node("strong", "", `Все оценки внесены. Итог ${n(course.earned_points)} / 100.`), node("p", "", "При необходимости можно исправить оценку ниже — расчёт обновится."));
    } else if (!scenario?.feasible) {
      calculation.append(node("strong", "", `Цель ${n(academic.selectedTarget)} недостижима: максимум ${pct(course.max_achievable)}.`), node("p", "", "Выбери более низкую ступень или проверь, верно ли введены веса и оценки."));
    } else {
      calculation.append(node("strong", "", `Для цели ${n(scenario.target)} нужно в среднем ${neededPct(scenario.required_average)} на оставшихся работах.`), node("p", "", "Баллы для каждой работы — в колонке «Нужно»."));
    }
    area.append(calculation);
    const scroll = node("div", "academic-table-wrap");
    const table = node("table", "academic-table");
    const head = node("thead");
    const headingRow = node("tr");
    const allHundred = (course.components || []).every((component) => maximumScore(component) === 100);
    ["Задание / экзамен", "Вес", allHundred ? "Оценка, %" : "Баллы", allHundred ? "Нужно, %" : "Нужно баллов"].forEach((text) => headingRow.append(node("th", "", text)));
    head.append(headingRow);
    const body = node("tbody");
    const planned = scenario?.balanced_plan || [];
    for (const component of course.components || []) {
      const row = node("tr");
      const title = node("td", "academic-table-main");
      title.append(node("strong", "", component.name));
      if (component.due_at) title.append(node("div", "muted", safeDate(component.due_at)));
      row.append(title, node("td", "", pct(component.weight)));
      const scoreCell = node("td");
      const form = node("form", "academic-score-form");
      const input = node("input");
      input.type = "number";
      input.min = "0";
      const maximum = maximumScore(component);
      input.max = String(maximum);
      input.step = "0.01";
      input.value = component.score == null ? "" : String(component.score);
      input.placeholder = "—";
      input.setAttribute("aria-label", maximum === 100 ? `Оценка за ${component.name}, процентов` : `Баллы за ${component.name}, из ${n(maximum, 6)}`);
      const save = node("button", "", "✓");
      save.type = "submit";
      save.setAttribute("aria-label", `Сохранить оценку за ${component.name}`);
      form.append(input, save);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        save.disabled = true;
        try {
          const score = input.value === "" ? null : Number(input.value);
          await request(`/courses/${encodeURIComponent(id)}/scores`, "PATCH", { component_id: component.id, score });
          const selected = academic.selectedTarget;
          await reloadAfterChange();
          openDetail(id, selected);
          notify("Оценка сохранена. Цели и приоритет пересчитаны.");
        } catch (error) { notify(error.message, true); }
        finally { save.disabled = false; }
      });
      scoreCell.append(form);
      if (!allHundred) scoreCell.append(node("small", "academic-score-max", "из " + n(maximum, 6)));
      row.append(scoreCell);
      const item = planned.find((entry) => String(entry.component_id ?? entry.id) === String(component.id));
      row.append(node("td", "academic-needed", component.score != null ? "Сдано" : scenario?.feasible && item ? neededScore(item) : "—"));
      body.append(row);
    }
    table.append(head, body);
    scroll.append(table);
    area.append(scroll);
    area.append(node("p", "academic-form-help", "Если в правилах вуза есть отдельный обязательный минимум на Final, учитывай его дополнительно. Здесь считаем общий итог по весам."));
    if (scenario?.feasible && planned.length) {
      const alternatives = node("details", "academic-details-source");
      alternatives.append(node("summary", "", "Можно ли набрать меньше на одной из работ?"), node("p", "", "Да, если компенсировать другими. Ниже — минимум каждой работы при 100% на всех остальных. Эти минимумы нельзя использовать одновременно."));
      planned.forEach((item) => alternatives.append(node("p", "", `${item.name}: ${neededScore(item, true)}`)));
      area.append(alternatives);
    }
    const source = node("details", "academic-details-source");
    source.append(node("summary", "", "Подробнее: формула, кредиты и источники"));
    source.append(node("p", "", typeof course.formula === "string" ? course.formula : "Итог = Σ (оценка / максимум × итоговый вес)."));
    const evidence = course.evidence;
    if (Array.isArray(evidence)) evidence.forEach((item) => source.append(node("p", "", typeof item === "string" ? item : JSON.stringify(item))));
    else if (evidence) source.append(node("p", "", typeof evidence === "string" ? evidence : JSON.stringify(evidence, null, 2)));
    source.append(node("p", "", `${n(course.credits)} кредитов · сложность ${n(course.difficulty, 0)}/5 · ${manualDifficulty(course) ? "твоя оценка" : "можно изменить"}. Оценено ${pct(course.completed_weight)} общего веса.`));
    (course.schedule_links || []).forEach((text) => source.append(node("p", "", text)));
    area.append(source);
    const footer = node("div", "academic-detail-footer");
    const remove = action("Удалить предмет", async () => {
      const approved = typeof confirmAction === "function" ? await confirmAction("Удалить предмет?", `Предмет «${course.name}» и введённые оценки будут удалены.`) : window.confirm(`Удалить предмет ${course.name}?`);
      if (!approved) return;
      try {
        await request(`/courses/${encodeURIComponent(id)}`, "DELETE");
        q("#academic-detail-dialog").close();
        await reloadAfterChange();
        notify("Предмет удалён. План обновлён.");
      } catch (error) { notify(error.message, true); }
    }, "button danger");
    footer.append(remove, action("Изменить веса и предмет", () => { q("#academic-detail-dialog").close(); openEditor(findCourse(id)); }, "button secondary"));
    area.append(footer);
    showDialog("#academic-detail-dialog");
  }

  function updateImportMode() {
    const kind = q("#academic-import-mode").value;
    academic.importKind = kind;
    const schedule = kind === "schedule";
    q("#academic-import-title").textContent = schedule ? "Добавить моё расписание" : kind === "combined" ? "Предмет и расписание — за один раз" : academic.importDraft ? "Силлабус: " + academic.importDraft.name : "Загрузить силлабус";
    q("#academic-import-description").textContent = schedule ? "Вставь дни недели и время или загрузи файл. Сначала покажем результат, затем ты подтвердишь сохранение." : "Вставь текст или выбери файл. Мы найдём работы и веса; перед сохранением всё можно проверить.";
    q("#academic-primary-label").textContent = schedule ? "Расписание занятий" : kind === "combined" ? "1. Силлабус — раздел с оцениванием" : "Силлабус — раздел с оцениванием";
    q("#academic-import-text").placeholder = schedule ? "Monday / Понедельник\n15:00–15:50 — Mathematics | lecture | C1.234\n\nИли даты: 26.10.2026 09:00–10:00 Mathematics" : "Название предмета (если есть) и раздел с заданиями, баллами и весами…";
    q("#academic-combined-schedule").hidden = kind !== "combined";
    q("#academic-import-year-wrap").hidden = kind === "syllabus";
    q("#academic-import-example").hidden = schedule;
    q("#academic-import-submit").textContent = "Распознать и проверить →";
  }

  function updateSourceMode(secondary = false) {
    const mode = q(secondary ? "#academic-schedule-source-mode" : "#academic-source-mode").value;
    const prefix = secondary ? "#academic-secondary" : "#academic-primary";
    q(prefix + "-file-wrap").hidden = mode !== "file";
    q(prefix + "-text-wrap").hidden = mode !== "text";
    const file = q(secondary ? "#academic-import-schedule-file" : "#academic-import-file");
    q(secondary ? "#academic-import-clear-schedule-file" : "#academic-import-clear-file").hidden = !file.files.length;
  }

  function openImport(kind = "combined", draft = null) {
    academic.importDraft = draft;
    q("#academic-import-form").reset();
    q("#academic-import-mode").value = kind;
    const today = new Date(localInput(new Date().toISOString()).slice(0, 10) + "T12:00:00Z");
    today.setUTCDate(today.getUTCDate() - (today.getUTCDay() + 6) % 7);
    q("#academic-import-anchor").value = today.toISOString().slice(0, 10);
    q(".academic-paste-option").open = false;
    updateImportMode(); updateSourceMode(); updateSourceMode(true);
    q("#academic-import-feedback").replaceChildren();
    q("#academic-schedule-preview").replaceChildren();
    showDialog("#academic-import-dialog");
  }

  function sourceValue(secondary = false) {
    const mode = q(secondary ? "#academic-schedule-source-mode" : "#academic-source-mode").value;
    return mode === "file" ? {file:q(secondary ? "#academic-import-schedule-file" : "#academic-import-file").files[0]} : {text:q(secondary ? "#academic-import-schedule-text" : "#academic-import-text").value.trim()};
  }

  async function readImportSource(source, kind) {
    if (!source.file && !source.text) return null;
    if (source.file && source.file.size > 5 * 1024 * 1024) throw new Error("Файл больше 5 МБ. Убери его кнопкой «Убрать выбранный файл» и вставь текст или выбери только нужные страницы.");
    const settings = {year:Number(q("#academic-import-year").value || 2026), anchor_date:q("#academic-import-anchor").value || null, weeks:Number(q("#academic-import-weeks").value || 12)};
    if (source.file) {
      const form = new FormData();
      form.append("file", source.file); form.append("kind", kind);
      Object.entries(settings).forEach(([key, value]) => { if (value != null) form.append(key, String(value)); });
      return request("/import/file", "POST", form);
    }
    return request("/import", "POST", {text:source.text, kind, ...settings});
  }

  function schedulePayload(data) {
    return {busy:data.busy || [], exams:data.exams || [], recurring:!!data.recurring, weekly_rules:data.weekly_rules || [], week_start:data.week_start || null, coverage_end:data.coverage_end || null, weeks:data.weeks || null};
  }

  function appendDraftChoice(area, data) {
    const existing = new Set(academic.courses.map((course) => course.name.trim().toLocaleLowerCase()));
    const names = [...new Set((data.courses || data.weekly_rules?.map((item) => item.title) || []).map((item) => typeof item === "string" ? item.trim() : item.name || item.title || "").filter(Boolean))].filter((name) => !existing.has(name.toLocaleLowerCase()));
    if (!names.length) return () => [];
    const box = node("fieldset", "academic-draft-choice");
    box.append(node("legend", "", "Добавить найденные предметы?"), node("p", "academic-form-help", "Выбери нужные. Они появятся без выдуманных оценок и весов; силлабус можно загрузить к каждому позже."));
    const inputs = names.map((name) => {
      const label = node("label", "academic-import-check");
      const input = node("input"); input.type = "checkbox"; input.checked = true;
      label.append(input, node("span", "", name)); box.append(label);
      return {name, input};
    });
    area.append(box);
    return () => inputs.filter((item) => item.input.checked).map((item) => item.name);
  }

  async function loadExample() {
    try {
      const data = await request("/example");
      q("#academic-import-dialog").close();
      openEditor(data.course, { ...data, warnings: ["Учебный пример из предоставленного силлабуса HPC. Это не твои реальные оценки.", ...(data.warnings || [])] });
    } catch (error) { notify(error.message, true); }
  }

  q("#academic-import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = q("#academic-import-submit");
    if (submit.disabled) return;
    const feedback = q("#academic-import-feedback");
    try {
      const primary = sourceValue();
      const secondary = academic.importKind === "combined" ? sourceValue(true) : {};
      if (!primary.file && !primary.text && !secondary.file && !secondary.text) throw new Error("Вставь текст или выбери файл хотя бы в одном разделе.");
      submit.disabled = true;
      event.target.setAttribute("aria-busy", "true");
      feedback.replaceChildren(node("p", "academic-source-notice", "Читаем документ… Для фото и сканов распознавание может занять чуть больше времени."));
      let data = await readImportSource(primary, academic.importKind === "schedule" ? "schedule" : "syllabus");
      let schedule = academic.importKind === "schedule" ? data : null;
      if (academic.importKind === "combined") {
        if (secondary.file || secondary.text) schedule = await readImportSource(secondary, "schedule");
        else if (primary.text && /\d{1,2}:\d{2}/.test(primary.text) && /Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье/i.test(primary.text)) schedule = await readImportSource(primary, "schedule");
        if (schedule && !schedule.busy?.length) throw new Error("В расписании не найдены занятия. Используй заголовок дня недели и время, например Monday · 15:00–15:50 — Mathematics. Текст и файлы остались в форме.");
      }
      feedback.replaceChildren();
      if (academic.importKind === "schedule" || !data) renderSchedulePreview(schedule);
      else {
        if (!data.course) throw new Error("Не удалось извлечь предмет. Попробуй вставить текст раздела с оцениванием.");
        if (academic.importDraft) {
          if (!data.course.name || data.course.name === "Новый предмет") data.course.name = academic.importDraft.name;
          data._draft_id = academic.importDraft.id;
          data._draft_name = academic.importDraft.name;
          if (data.course.name.trim().toLocaleLowerCase() !== academic.importDraft.name.trim().toLocaleLowerCase()) data.warnings = [...(data.warnings || []), `Выбран предмет «${academic.importDraft.name}», но в документе найдено «${data.course.name}». Проверь название. Если сохранишь другой предмет, исходный черновик останется.`];
        }
        if (schedule?.busy?.length) data._schedule = schedule;
        q("#academic-import-dialog").close();
        openEditor(data.course, data);
      }
    } catch (error) { feedback.replaceChildren(node("p", "academic-error", error.message)); }
    finally { submit.disabled = false; event.target.setAttribute("aria-busy", "false"); }
  });

  function renderSchedulePreview(data) {
    const area = q("#academic-schedule-preview");
    area.replaceChildren();
    const items = data?.busy || [];
    const notice = node("div", "academic-source-notice");
    notice.append(node("p", "", data?.recurring ? `Распознано ${data.weekly_rules.length} занятий в неделю. Повторение: ${data.weeks} недель, ${data.week_start} — ${data.coverage_end}. Всего событий: ${items.length}. Подтверждение заменит ранее загруженное расписание.` : `Распознано занятых окон: ${items.length}. Проверь даты, год и время. Это отдельные датированные события. Подтверждение заменит ранее загруженное расписание.`));
    (data.warnings || []).forEach((warning) => notice.append(node("p", "", `• ${warning}`)));
    area.append(notice);
    if (!items.length) return;
    const chooseDrafts = appendDraftChoice(area, data);
    const editable = node("details", "academic-schedule-rows");
    editable.append(node("summary", "", `Проверить даты и занятия (${items.length})`));
    const entries = [];
    items.forEach((item, index) => {
      const row = node("div", "academic-schedule-event");
      const fields = node("div", "academic-schedule-fields");
      const title = node("input");
      title.value = item.title || "Занято";
      title.setAttribute("aria-label", "Название события");
      title.maxLength = 160;
      const start = node("input");
      start.type = "datetime-local";
      start.value = localInput(item.start, data.timezone || academic.settings.timezone);
      start.setAttribute("aria-label", "Начало события");
      const end = node("input");
      end.type = "datetime-local";
      end.value = localInput(item.end, data.timezone || academic.settings.timezone);
      end.setAttribute("aria-label", "Конец события");
      fields.append(title, start, end);
      const exam = (data.exams || []).find((entry) => entry.due_at === item.start || entry.title === item.title || entry.course === item.title);
      const meta = node("div", "academic-schedule-exam");
      const kindLabel = node("label", "", "Тип события");
      const kind = node("select");
      for (const [value, label] of [["", "Занятие / встреча"], ["exam", "Экзамен · тип неизвестен"], ["final", "Final · итоговый экзамен"], ["midterm", "Midterm"], ["endterm", "Endterm"]]) {
        const option = node("option", "", label);
        option.value = value;
        kind.append(option);
      }
      kind.value = exam?.assessment_kind || (exam ? "exam" : "");
      kindLabel.append(kind);
      const courseLabel = node("label", "", "Предмет для дедлайна");
      const course = node("input");
      course.value = exam?.course || item.title || "";
      course.maxLength = 160;
      course.setAttribute("aria-label", "Предмет для привязки экзамена");
      courseLabel.append(course);
      courseLabel.hidden = !kind.value;
      kind.addEventListener("change", () => { courseLabel.hidden = !kind.value; });
      meta.append(kindLabel, courseLabel);
      fields.append(meta);
      const entry = { item, title, start, end, kind, course, exam, removed: false, index };
      entries.push(entry);
      row.append(fields, action("×", () => { entry.removed = true; row.remove(); }, "icon-button"));
      editable.append(row);
    });
    area.append(editable);
    const confirm = node("div", "academic-schedule-confirm");
    const save = action("Подтвердить расписание", async () => {
      save.disabled = true;
      try {
        const active = entries.filter((entry) => !entry.removed);
        const timezone = data.timezone || academic.settings.timezone || "Asia/Almaty";
        const busy = active.map((entry) => ({ start: isoInput(entry.start.value, timezone), end: isoInput(entry.end.value, timezone), title: entry.title.value.trim() || "Занято" }));
        if (!busy.length) throw new Error("Добавь хотя бы одно занятое окно.");
        if (busy.some((item) => !item.start || !item.end || new Date(item.start) >= new Date(item.end))) throw new Error("Проверь время: конец каждого события должен быть позже начала.");
        const exams = active.filter((entry) => entry.kind.value).map((entry) => ({ title: entry.title.value.trim() || entry.item.title || "Экзамен", course: entry.course.value.trim() || entry.title.value.trim(), due_at: isoInput(entry.start.value, timezone), assessment_kind: entry.kind.value, source_quote: entry.exam?.source_quote || null }));
        if (exams.some((exam) => !exam.course)) throw new Error("Укажи название предмета для каждого экзамена, чтобы связать его с заданием.");
        await request("/schedule", "POST", { ...schedulePayload(data), busy, exams });
        const names = chooseDrafts();
        if (names.length) await request("/course-drafts", "POST", {names});
        q("#academic-import-dialog").close();
        await reloadAfterChange();
        notify("Расписание сохранено. Занятые часы учтены, выбранные предметы появились в «Моей учёбе».");
      } catch (error) { q("#academic-import-feedback").replaceChildren(node("p", "academic-error", error.message)); }
      finally { save.disabled = false; }
    }, "button primary");
    confirm.append(save);
    area.append(confirm);
  }

  function openSettings() {
    const settings = academic.settings;
    q("#academic-daily-minutes").value = settings.daily_minutes ?? 180;
    q("#academic-start-hour").value = settings.start_hour ?? 16;
    q("#academic-end-hour").value = settings.end_hour ?? 22;
    q("#academic-preferred-target").value = settings.preferred_target ?? 95;
    q("#academic-min-target").value = settings.min_target ?? 70;
    const saved = q("#academic-saved-schedule");
    saved.replaceChildren();
    const busy = academic.importedSchedule?.busy || [];
    if (!busy.length) saved.append(node("p", "academic-form-help", "Расписание пока не загружено. Занятые часы также учитываются из подключённого Google Calendar и настроек недели."));
    else {
      for (const item of busy.slice(0, 20)) {
        const row = node("div", "academic-schedule-event");
        row.append(node("strong", "", item.title), node("time", "", `${safeDate(item.start)} · ${clockLabel(item.start)}–${clockLabel(item.end)}`));
        saved.append(row);
      }
      saved.append(action("Заменить расписание", () => { q("#academic-time-dialog").close(); openImport("schedule"); }, "text-button"));
      saved.append(action("Убрать загруженное расписание", async () => {
        const approved = typeof confirmAction === "function" ? await confirmAction("Убрать расписание?", "Загруженные занятые окна перестанут ограничивать учебный план. Предметы и оценки сохранятся.") : window.confirm("Убрать загруженное расписание?");
        if (!approved) return;
        try {
          await request("/schedule", "POST", { busy: [], exams: [] });
          await reloadAfterChange();
          openSettings();
          notify("Загруженное расписание убрано. План перестроен.");
        } catch (error) { errorAt("#academic-time-error", error); }
      }, "text-button"));
    }
    const scaleArea = q("#academic-grade-scale");
    scaleArea.replaceChildren();
    for (const band of settings.grade_scale || []) {
      const row = node("div", "academic-scale-row");
      row._band = { ...band };
      const threshold = node("input");
      threshold.type = "number";
      threshold.min = "0";
      threshold.max = "100";
      threshold.step = "0.1";
      threshold.value = band.min_score;
      threshold.dataset.scale = "min_score";
      threshold.setAttribute("aria-label", "Порог оценки, процентов");
      const letter = node("input");
      letter.value = band.letter;
      letter.maxLength = 20;
      letter.dataset.scale = "letter";
      letter.setAttribute("aria-label", "Буквенная оценка");
      const gpa = node("input");
      gpa.type = "number";
      gpa.min = "0";
      gpa.max = "5";
      gpa.step = "0.01";
      gpa.value = band.gpa;
      gpa.dataset.scale = "gpa";
      gpa.setAttribute("aria-label", `GPA для оценки от ${band.min_score}`);
      row.append(threshold, letter, gpa);
      scaleArea.append(row);
    }
    errorAt("#academic-time-error", null);
    showDialog("#academic-time-dialog");
  }

  q("#academic-time-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = q('button[type="submit"]', event.target);
    if (save.disabled) return;
    try {
      const body = { daily_minutes: Number(q("#academic-daily-minutes").value), start_hour: Number(q("#academic-start-hour").value), end_hour: Number(q("#academic-end-hour").value), preferred_target: Number(q("#academic-preferred-target").value), min_target: Number(q("#academic-min-target").value) };
      const scaleRows = all(".academic-scale-row", q("#academic-grade-scale"));
      if (scaleRows.length) body.grade_scale = scaleRows.map((row) => ({ min_score: Number(q('[data-scale="min_score"]', row).value), letter: q('[data-scale="letter"]', row).value.trim(), gpa: Number(q('[data-scale="gpa"]', row).value), label: row._band.label || "" }));
      if (body.start_hour >= body.end_hour) throw new Error("Время окончания должно быть позже начала.");
      if (body.min_target > body.preferred_target) throw new Error("Нижняя ступень не может быть выше основной цели.");
      save.disabled = true;
      event.target.setAttribute("aria-busy", "true");
      save.textContent = "Перестраиваем план…";
      await request("/settings", "PUT", body);
      q("#academic-time-dialog").close();
      await reloadAfterChange();
      notify("Настройки сохранены. План перестроен.");
    } catch (error) { errorAt("#academic-time-error", error); }
    finally { save.disabled = false; save.textContent = "Перестроить план"; event.target.setAttribute("aria-busy", "false"); }
  });

  for (let hour = 0; hour <= 23; hour++) {
    const start = node("option", "", `${String(hour).padStart(2, "0")}:00`);
    start.value = hour;
    q("#academic-start-hour").append(start);
    const end = node("option", "", `${String(hour + 1).padStart(2, "0")}:00`);
    end.value = hour + 1;
    q("#academic-end-hour").append(end);
  }
  q("#academic-add").addEventListener("click", () => openEditor());
  q("#academic-component-add").addEventListener("click", () => componentRow());
  q("#academic-import").addEventListener("click", () => openImport("syllabus"));
  q("#academic-schedule-import").addEventListener("click", () => openImport("schedule"));
  q("#academic-settings").addEventListener("click", openSettings);
  q("#academic-import-example").addEventListener("click", loadExample);
  q("#academic-import-mode").addEventListener("change", updateImportMode);
  for (const secondary of [false, true]) {
    q(secondary ? "#academic-schedule-source-mode" : "#academic-source-mode").addEventListener("change", () => updateSourceMode(secondary));
    q(secondary ? "#academic-import-schedule-file" : "#academic-import-file").addEventListener("change", () => { updateSourceMode(secondary); q("#academic-import-feedback").replaceChildren(); });
    q(secondary ? "#academic-import-clear-schedule-file" : "#academic-import-clear-file").addEventListener("click", () => {
      q(secondary ? "#academic-import-schedule-file" : "#academic-import-file").value = "";
      q(secondary ? "#academic-schedule-source-mode" : "#academic-source-mode").value = "text";
      updateSourceMode(secondary);
      q("#academic-import-feedback").replaceChildren();
      notify("Файл убран. Можно вставить текст или выбрать другой файл.");
    });
  }
  q("#header-study-settings").addEventListener("click", async () => { await load(); openSettings(); });
  q("#settings-study-time").addEventListener("click", async () => { await load(); openSettings(); });
  q("#settings-start-study").addEventListener("click", async () => { await showView("academic"); openImport("combined"); });
  q("#academic-how").addEventListener("click", () => {
    const copy = node("div");
    copy.append(node("p", "", "Система поднимает выше предметы, где сложнее достичь цели и ближе дедлайны. Кредиты показывают влияние предмета на GPA, сложность — сколько подготовки ему может понадобиться."), node("p", "", "После каждой новой оценки приоритет и план пересчитываются. Автоматическая сложность — предварительная оценка по названию предмета и успеваемости. В редакторе можно указать свою сложность от 1 до 5."), node("p", "", "Причины сортировки показаны на карточках. Рекомендация помогает выбрать следующий шаг, но не оценивает способности студента."));
    showExplanation("Почему этот предмет первый?", copy);
  });
  async function importMaterial(materialId) {
    try {
      await load();
      const response = await fetch(`/api/materials/${encodeURIComponent(materialId)}`);
      if (!response.ok) throw new Error("Не удалось открыть материал. Обнови страницу и попробуй снова.");
      const material = await response.json();
      const text = (material.pages || []).map((page) => page.text || "").join("\n\n");
      if (!text.trim()) throw new Error("В материале нет текста. Загрузи PDF с текстовым слоем или вставь текст силлабуса.");
      const data = await request("/import", "POST", { text, kind: "syllabus" });
      if (!data.course) throw new Error("Не удалось определить схему оценивания. Добавь предмет вручную.");
      openEditor(data.course, data);
    } catch (error) { notify(error.message, true); }
  }
  window.CampusAcademic = { load, importMaterial, changeDemo, loadDemoStatus, openImport, openSettings, renderProgress:renderAcademicProgress };
  window.addEventListener("hashchange", () => { if (location.hash === "#academic") load(); });
  if (location.hash === "#academic") load();
})();
