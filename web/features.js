"use strict";
// All user data is rendered as text. All business calculations come from Python.
function safeCalendarUrl(value) {
  try {
    const u = new URL(value);
    return (
      u.protocol === "https:" &&
      ["calendar.google.com", "www.google.com"].includes(u.hostname)
    );
  } catch {
    return false;
  }
}
function selectPractice(kind) {
  $$("[data-practice]").forEach((b) => {
    const selected = b.dataset.practice === kind;
    b.classList.toggle("selected", selected);
    b.setAttribute("aria-pressed", String(selected));
  });
  ["quests", "grades", "code"].forEach(
    (k) => ($("#practice-" + k).hidden = k !== kind),
  );
}
function sendFeatureMessage(message) {
  if (state.sending) {
    toast("Дождись предыдущего ответа", true);
    return;
  }
  showView("chat");
  $("#chat-input").value = message;
  $("#chat-form").requestSubmit();
}
async function featureRequest(form, action, output) {
  const submit = $('button[type="submit"]', form);
  if (submit?.disabled) return;
  if (submit) submit.disabled = true;
  form.setAttribute("aria-busy", "true");
  try {
    await action();
  } catch (e) {
    if (output) output.replaceChildren(el("p", "risk", e.message));
    toast(e.message, true);
  } finally {
    if (submit) submit.disabled = false;
    form.setAttribute("aria-busy", "false");
  }
}
function quoteCard(source) {
  const card = el("article", "quote-card");
  card.append(
    el(
      "small",
      "",
      `${source.file} · стр. ${source.page} · строка ${source.line}`,
    ),
    el("blockquote", "", source.quote),
  );
  card.append(
    whyButton(source.why),
    button("Открыть строку ↗", () => openSource(source), "text-button"),
  );
  return card;
}
async function openSource(source) {
  try {
    const material = await api("/materials/" + source.material_id);
    $("#material-name").textContent =
      material.name + " · страница " + source.page;
    const area = $("#material-content");
    area.replaceChildren();
    const page = material.pages.find((p) => p.page === source.page);
    if (!page) throw new Error("Страница недоступна");
    page.text
      .split("\n")
      .forEach((line, i) =>
        area.append(
          el(
            "pre",
            i + 1 === source.line ? "cited-line" : "source-line",
            `${i + 1} │ ${line}`,
          ),
        ),
      );
    $("#material-dialog").showModal();
    $(".cited-line", area)?.scrollIntoView({ block: "center" });
  } catch (e) {
    toast(e.message, true);
  }
}
async function showSyllabus(material) {
  const area = $("#syllabus-results");
  area.replaceChildren(el("p", "muted", "Ищу задания и явные сроки…"));
  $("#syllabus-dialog").showModal();
  try {
    const result = await api("/materials/" + material.id + "/syllabus");
    area.replaceChildren(whyButton(result.why));
    if (!result.candidates.length)
      area.append(
        el(
          "p",
          "muted",
          "Строки с заданиями не найдены. Открой материал и добавь задание вручную; даты из предположений не подставляются.",
        ),
      );
    result.candidates.forEach((c) => {
      const card = quoteCard(c.source);
      card.append(
        el("p", "muted", c.note),
        el("p", "", "Нужно заполнить: " + c.missing.join(", ")),
      );
      card.append(
        button("Проверить и добавить задание", () => {
          $("#syllabus-dialog").close();
          openTask({
            ...c,
            id: null,
            notes: `Источник: ${c.source.file}, стр. ${c.source.page}, строка ${c.source.line}`,
          });
          if (!c.due_at && c.date)
            $("#task-due").value = c.date + "T" + (c.time || "");
        }),
      );
      area.append(card);
    });
    if (result.grading_rules.length)
      area.append(el("h3", "", "Правила оценивания"));
    result.grading_rules.forEach((source) => {
      const card = quoteCard(source);
      card.append(
        button("Создать предмет из силлабуса", () => {
          $("#syllabus-dialog").close();
          showView("academic");
          window.CampusAcademic?.importMaterial(material.id);
        }),
      );
      area.append(card);
    });
  } catch (e) {
    area.replaceChildren(el("p", "risk", e.message));
  }
}
function renderCalendar() {
  const google = state.google || {};
  $("#calendar-status").textContent = google.connected
    ? "Google подключён"
    : google.configured ? "Можно подключить Google" : "Доступен экспорт .ics";
  $("#calendar-connect").hidden = !!google.connected;
  $("#calendar-connect").disabled = !google.configured;
  $("#calendar-connect").textContent = google.configured
    ? "Подключить Google Calendar"
    : "Вход Google ещё не настроен";
  $("#calendar-disconnect").hidden = !google.connected;
  $("#calendar-sync").disabled = !google.connected;
  $("#calendar-message").textContent = google.connected
    ? "Основной календарь. При построении плана занятые часы обновляются из Google."
    : google.configured
      ? "Войди в Google, чтобы добавлять события. Пароль и API-ключ в приложении не нужны."
      : "Вход Google ещё не настроен владельцем приложения. Запрос на событие можно подготовить; добавление станет доступно после подключения.";
  const draft = $("#calendar-draft");
  draft.replaceChildren();
  if (state.calendar_draft) {
    const d = state.calendar_draft;
    draft.append(
      el("strong", "", "Незавершённый запрос: " + (d.title || "Событие")),
      el(
        "p",
        "muted",
        `${d.date || "дата не указана"} · ${d.time || "время не указано"} · ${d.timezone}`,
      ),
    );
    draft.append(
      button(
        d.start ? "Добавить подготовленное событие" : "Уточнить в чате",
        () => {
          if (d.start) sendFeatureMessage("сохрани");
          else {
            showView("chat");
            $("#chat-input").placeholder = "Укажи день и время события";
          }
        },
      ),
      button(
        "Отменить запрос",
        () => sendFeatureMessage("отмена"),
        "text-button",
      ),
    );
  }
  const events = $("#calendar-events");
  events.replaceChildren();
  const cache = state.calendar_cache;
  if (cache) {
    events.append(
      el(
        "p",
        "muted",
        "События на ближайшие 15 дней · получено " +
          dateLabel(cache.fetched_at) +
          " " +
          timeLabel(cache.fetched_at),
      ),
      whyButton(cache.why),
    );
    if (!cache.events.length)
      events.append(el("p", "muted", "В этом диапазоне событий нет."));
    cache.events.slice(0, 30).forEach((e) => {
      const row = el("div", "event-row");
      row.append(
        el("strong", "", e.title),
        el(
          "span",
          "muted",
          `${dateLabel(e.start)} · ${e.all_day ? "весь день" : timeLabel(e.start) + "–" + timeLabel(e.end)}`,
        ),
      );
      if (safeCalendarUrl(e.url)) {
        const link = el("a", "text-button", "Открыть ↗");
        link.href = e.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        row.append(link);
      }
      events.append(row);
    });
    if (cache.events.length > 30)
      events.append(
        el(
          "p",
          "muted",
          "Показаны первые 30 событий; план учитывает весь полученный диапазон.",
        ),
      );
  }
}
function renderGradeSource() {
  const area = $("#grade-source");
  area.replaceChildren();
  if (state.gradeSource) {
    area.append(
      quoteCard(state.gradeSource),
      button(
        "Убрать ссылку на силлабус",
        () => {
          state.gradeSource = null;
          renderGradeSource();
        },
        "text-button",
      ),
    );
  }
}
function addGradeRow(value = {}, unknown = false) {
  const row = el("div", "grade-row");
  function field(label, name, type, initial, attributes = {}) {
    const box = el("label", "", label);
    const input = el("input");
    input.type = type;
    input.dataset.field = name;
    if (initial !== undefined && initial !== null) input.value = initial;
    Object.entries(attributes).forEach(([k, v]) => input.setAttribute(k, v));
    box.append(input);
    row.append(box);
    return input;
  }
  field("Компонент", "name", "text", value.name || "", {
    required: "",
    maxlength: "80",
    placeholder: "Название",
  });
  field("Вес, %", "weight", "number", value.weight, {
    required: "",
    min: "0.01",
    max: "100",
    step: "0.01",
  });
  const score = field("Балл", "score", "number", value.score, {
    required: "",
    min: "0",
    step: "0.01",
  });
  field("Из скольких", "max_score", "number", value.max_score ?? 100, {
    required: "",
    min: "0.01",
    max: "100000",
    step: "0.01",
  });
  const radioLabel = el("label", "check-label", "Ищем");
  const radio = el("input");
  radio.type = "radio";
  radio.name = "grade-unknown";
  radio.checked = unknown;
  radio.setAttribute("aria-label", "Найти балл для этого компонента");
  radioLabel.prepend(radio);
  row.append(radioLabel);
  radio.onchange = syncGradeUnknown;
  row.append(
    button(
      "×",
      () => {
        if ($$(".grade-row").length <= 2) {
          toast("Нужны минимум два компонента");
          return;
        }
        row.remove();
        if (!$('input[name="grade-unknown"]:checked'))
          $('input[name="grade-unknown"]').checked = true;
        syncGradeUnknown();
      },
      "icon-button",
    ),
  );
  $("#grade-rows").append(row);
  syncGradeUnknown();
}
function syncGradeUnknown() {
  $$(".grade-row").forEach((row) => {
    const unknown = $('input[type="radio"]', row).checked;
    const score = $('[data-field="score"]', row);
    score.disabled = unknown;
    score.required = !unknown;
    score.placeholder = unknown ? "?" : "";
  });
}
function renderQuestSession(q) {
  state.activeQuest = q;
  const area = $("#quest-session");
  area.replaceChildren();
  const status = el("div", "quest-score");
  status.append(
    el("span", "eyebrow", q.material),
    el(
      "h3",
      "",
      q.finished
        ? "Тренировка завершена"
        : `Вопрос ${q.answered + 1} из ${q.total}`,
    ),
    el(
      "p",
      "",
      `Правильных ответов: ${q.correct} / ${q.total} · ${q.score_percent}%`,
    ),
    whyButton(q.why),
  );
  area.append(status);
  if (q.feedback) {
    const f = q.feedback;
    const card = el("div", "quest-feedback" + (f.correct ? " correct" : ""));
    card.append(
      el("strong", "", f.correct ? "Верно ✓" : "Повторим этот факт"),
      el("p", "", "Эталон: " + f.expected),
      whyButton(f.why),
      quoteCard(f.source),
    );
    area.append(card);
  }
  if (!q.finished) {
    const form = el("form", "quest-answer-form");
    const label = el("label", "", q.question.question);
    const input = el("input");
    input.required = true;
    input.maxLength = 300;
    input.autocomplete = "off";
    input.placeholder = "Восстанови термин";
    label.append(input);
    const submit = el("button", "button primary", "Проверить ответ");
    submit.type = "submit";
    form.append(label, submit);
    form.onsubmit = (e) => {
      e.preventDefault();
      featureRequest(
        form,
        async () => {
          const before = state.progress.xp;
          const result = await api(`/quests/${q.id}/answers`, {
            method: "POST",
            body: JSON.stringify({
              question_id: q.question.id,
              answer: input.value,
            }),
          });
          renderQuestSession(result);
          await refresh();
          if (state.progress.xp > before) celebrate(state.progress.xp - before);
        },
        area,
      );
    };
    area.append(form);
  } else
    area.append(
      el(
        "p",
        "muted",
        "Ошибки можно повторить в новой тренировке. Повторные правильные ответы на тот же факт не добавляют XP.",
      ),
    );
}
function renderFeatures() {
  renderCalendar();
  const select = $("#quest-material"),
    current = select.value;
  select.replaceChildren(el("option", "", "Выбери материал"));
  select.firstChild.value = "";
  state.materials.forEach((m) => {
    const o = el("option", "", m.name);
    o.value = m.id;
    select.append(o);
  });
  select.value = current;
  if (!state.gradeInitialized) {
    const config = state.grade_config;
    (
      config?.components || [
        { name: "Текущая работа" },
        { name: "Промежуточный" },
        { name: "Финал" },
      ]
    ).forEach((v, i, a) =>
      addGradeRow(v, config ? v.score === null : i === a.length - 1),
    );
    if (config) {
      $("#grade-target").value = config.target;
      state.gradeSource = config.source;
    }
    state.gradeInitialized = true;
    renderGradeSource();
  }
  const resume = $("#quest-resume");
  resume.replaceChildren();
  const unfinished = (state.quests || []).filter(
    (q) => q.answered < q.total && q.id !== state.activeQuest?.id,
  );
  unfinished.slice(-3).forEach((q) =>
    resume.append(
      button(
        `Продолжить: ${q.material} (${q.answered}/${q.total})`,
        async () => {
          try {
            renderQuestSession(await api("/quests/" + q.id));
          } catch (e) {
            toast(e.message, true);
          }
        },
        "text-button",
      ),
    ),
  );
  if (
    state.google_notice?.text &&
    state.lastGoogleNotice !== state.google_notice.text
  ) {
    toast(state.google_notice.text);
    state.lastGoogleNotice = state.google_notice.text;
  }
}
function initFeatures() {
  $("#material-note-open").onclick = openNoteDialog;
  $("#material-note-form").onsubmit = (event) => {
    event.preventDefault();
    featureRequest(event.target, async () => {
      const name = $("#material-note-name").value.trim();
      const text = $("#material-note-text").value.trim();
      if (!name || text.length < 10) throw new Error("Добавь название и текст конспекта (не меньше 10 символов).");
      const filename = name.replace(/[\\/:*?"<>|]/g, "_").slice(0, 100) + ".txt";
      const form = new FormData();
      form.append("file", new File([text], filename, {type:"text/plain;charset=utf-8"}));
      await api("/materials", {method:"POST", body:form});
      $("#material-note-dialog").close();
      await refresh();
      toast("Конспект сохранён. Теперь доступны поиск цитат и тренировка.");
    }, $("#material-note-error"));
  };
  $$("[data-practice]").forEach(
    (b) => (b.onclick = () => selectPractice(b.dataset.practice)),
  );
  $("#event-form").onsubmit = (e) => {
    e.preventDefault();
    let message = $("#event-message").value.trim();
    if (!/^(запланируй|запланировать|создай|добавь)/i.test(message))
      message = "Запланируй " + message;
    sendFeatureMessage(message);
  };
  $("#calendar-connect").onclick = async () => {
    const b = $("#calendar-connect");
    b.disabled = true;
    try {
      const result = await api("/google/connect", { method: "POST" });
      const url = new URL(result.url);
      if (url.origin !== "https://accounts.google.com")
        throw new Error("Некорректный адрес входа");
      location.assign(result.url);
    } catch (e) {
      $("#calendar-message").textContent = e.message;
      toast(e.message, true);
    } finally {
      b.disabled = false;
    }
  };
  $("#calendar-sync").onclick = async () => {
    const b = $("#calendar-sync");
    b.disabled = true;
    try {
      await api("/calendar/sync", { method: "POST" });
      await refresh();
    } catch (e) {
      toast(e.message, true);
    } finally {
      b.disabled = !state.google?.connected;
    }
  };
  $("#calendar-disconnect").onclick = async () => {
    try {
      const r = await api("/google/disconnect", { method: "POST" });
      await refresh();
      toast(
        r.revoked
          ? "Google Calendar отключён. События сохранены."
          : "Разрешение удалено из приложения. Отзыв в Google не подтверждён; проверь настройки аккаунта.",
      );
    } catch (e) {
      toast(e.message, true);
    }
  };
  $("#scenario-form").onsubmit = (e) => {
    e.preventDefault();
    featureRequest(
      e.target,
      async () => {
        const r = await api("/scenarios", {
          method: "POST",
          body: JSON.stringify({
            daily_minutes: Number($("#scenario-minutes").value),
            delay_days: Number($("#scenario-delay").value),
            days: Number($("#scenario-days").value),
          }),
        });
        const area = $("#scenario-result");
        area.replaceChildren();
        const comparison = el("div", "scenario-comparison");
        for (const [label, p] of [
          ["Сейчас", r.before],
          ["С изменениями", r.after],
        ]) {
          const card = el("div", "comparison-card");
          card.append(
            el("small", "", label),
            el("strong", "", `${p.scheduled_minutes} мин`),
            el("span", "muted", `Рисков: ${p.risks.length}`),
          );
          comparison.append(card);
        }
        area.append(comparison, whyButton(r.why));
        if (!r.changes.length)
          area.append(
            el("p", "muted", "Учебные блоки не изменились при этих условиях."),
          );
        r.changes.forEach((c) => {
          const details = el("details", "scenario-change");
          details.append(el("summary", "", c.title));
          for (const [name, blocks] of [
            ["Было", c.before],
            ["Стало", c.after],
          ])
            details.append(
              el(
                "p",
                "",
                name +
                  ": " +
                  (blocks
                    .map(
                      (s) =>
                        `${dateLabel(s.start)} ${timeLabel(s.start)}–${timeLabel(s.end)}`,
                    )
                    .join("; ") || "нет блоков"),
              ),
            );
          area.append(details);
        });
        r.after.risks.forEach((risk) => {
          const row = el(
            "p",
            "risk",
            `${risk.title}: ${risk.reason}. Не распределено ${risk.unscheduled_minutes} мин.`,
          );
          row.append(whyButton(risk.why));
          area.append(row);
        });
      },
      $("#scenario-result"),
    );
  };
  $("#material-search-form").onsubmit = (e) => {
    e.preventDefault();
    featureRequest(
      e.target,
      async () => {
        const r = await api("/materials/search", {
          method: "POST",
          body: JSON.stringify({ query: $("#material-query").value }),
        });
        const area = $("#search-results");
        area.replaceChildren(
          el(
            "p",
            "muted",
            `Найдено ${r.total_matches}; показано ${r.matches.length}.`,
          ),
          whyButton(r.why),
        );
        if (!r.matches.length)
          area.append(
            el(
              "p",
              "",
              "Совпадений по словам нет. Попробуй другие термины или загрузи нужный материал.",
            ),
          );
        r.matches.forEach((m) => area.append(quoteCard(m)));
        r.possible_differences.forEach((d) => {
          const box = el("div", "risk", d.note);
          box.append(quoteCard(d.a), quoteCard(d.b));
          area.append(box);
        });
      },
      $("#search-results"),
    );
  };
  $("#grade-add").onclick = () => {
    if ($$(".grade-row").length < 20) addGradeRow();
  };
  $("#grade-form").onsubmit = (e) => {
    e.preventDefault();
    featureRequest(
      e.target,
      async () => {
        const components = $$(".grade-row").map((row) => ({
          name: $('[data-field="name"]', row).value,
          weight: Number($('[data-field="weight"]', row).value),
          max_score: Number($('[data-field="max_score"]', row).value),
          score: $('input[type="radio"]', row).checked
            ? null
            : Number($('[data-field="score"]', row).value),
        }));
        const r = await api("/grades", {
          method: "POST",
          body: JSON.stringify({
            target: Number($("#grade-target").value),
            components,
            source: state.gradeSource || null,
            confirmed: $("#grade-confirm").checked,
          }),
        });
        const area = $("#grade-result");
        area.replaceChildren(
          el("div", "result-number", `${r.required_score} / ${r.max_score}`),
          el("p", "", `Нужно за «${r.component}» для цели ${r.target}.`),
          whyButton(r.why),
        );
        if (!r.achievable)
          area.append(
            el(
              "p",
              "risk",
              `Цель недостижима при этих данных. Максимальная итоговая оценка: ${r.maximum_final}.`,
            ),
          );
        if (r.already_reached)
          area.append(
            el(
              "p",
              "muted",
              "По взвешенной сумме цель достигнута. Проверь обязательные пороги и условия сдачи курса.",
            ),
          );
      },
      $("#grade-result"),
    );
  };
  $("#code-form").onsubmit = (e) => {
    e.preventDefault();
    featureRequest(
      e.target,
      async () => {
        const r = await api("/diagnostics", {
          method: "POST",
          body: JSON.stringify({
            code: $("#code-input").value,
            language: $("#code-language").value,
            filename: $("#code-name").value,
          }),
        });
        const area = $("#code-result");
        area.replaceChildren(
          el(
            "h3",
            "",
            r.syntax_ok
              ? "Синтаксис в порядке"
              : "Найдена синтаксическая ошибка",
          ),
          whyButton(r.why),
        );
        r.issues.forEach((i) => {
          const card = el("div", "quote-card");
          card.append(
            el("strong", "", `${r.filename}:${i.line}:${i.column}`),
            el("p", "", i.message),
            el("p", "muted", i.hint || ""),
            el("pre", "", i.quote),
            whyButton(i.why),
          );
          area.append(card);
        });
        area.append(
          el(
            "p",
            "muted",
            "Это результат парсера. Проверка алгоритма и запуск тестов не выполнялись.",
          ),
        );
      },
      $("#code-result"),
    );
  };
  $("#quest-source-form").onsubmit = (e) => {
    e.preventDefault();
    featureRequest(
      e.target,
      async () => {
        const mid = $("#quest-material").value;
        const r = await api(`/materials/${mid}/quests`);
        const area = $("#quest-bank");
        area.replaceChildren(whyButton(r.why));
        if (!r.questions.length) {
          area.append(
            el(
              "p",
              "muted",
              "Не найдены строки вида «Термин: определение». Добавь конспект с такими строками или выбери другой материал.",
            ),
          );
          return;
        }
        const form = el("form", "quest-bank-form");
        const selected = [];
        r.questions.forEach((q, i) => {
          const card = quoteCard(q.source);
          const label = el("label", "check-label", q.question);
          const check = el("input");
          check.type = "checkbox";
          check.checked = i < 5;
          label.prepend(check);
          card.prepend(label);
          card.append(el("p", "", "Эталон: " + q.answer));
          form.append(card);
          selected.push({ id: q.id, check });
        });
        const label = el(
          "label",
          "check-label",
          "Я проверил(а) вопросы и эталоны по цитатам",
        );
        const confirm = el("input");
        confirm.type = "checkbox";
        confirm.required = true;
        label.prepend(confirm);
        const submit = el("button", "button primary", "Начать квест →");
        submit.type = "submit";
        form.append(label, submit);
        area.append(form);
        form.onsubmit = (event) => {
          event.preventDefault();
          featureRequest(
            form,
            async () => {
              const ids = selected
                .filter((q) => q.check.checked)
                .map((q) => q.id);
              if (!ids.length) throw new Error("Выбери хотя бы один вопрос");
              const q = await api("/quests", {
                method: "POST",
                body: JSON.stringify({
                  material_id: mid,
                  question_ids: ids,
                  confirmed: confirm.checked,
                }),
              });
              area.replaceChildren();
              renderQuestSession(q);
              await refresh();
            },
            area,
          );
        };
      },
      $("#quest-bank"),
    );
  };
}

function openNoteDialog() {
  $("#material-note-form").reset();
  $("#material-note-error").replaceChildren();
  $("#material-note-error").hidden = false;
  $("#material-note-dialog").showModal();
  $("#material-note-name").focus();
}
