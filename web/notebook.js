"use strict";

(() => {
  const q = (selector, parent = document) => parent.querySelector(selector);
  const model = { materials: [], notebooks: [], selected: new Set(), current: null, initialized: false, pending: null, preparing:null, generating:false, userRequestedNew:false, restoring:false, restoreVersion:0 };
  const make = (tag, className, text) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  };
  const click = (text, callback, className = "text-button") => {
    const item = make("button", className, text);
    item.type = "button";
    item.addEventListener("click", callback);
    return item;
  };
  const status = (text = "", error = false) => {
    q("#notebook-status").textContent = text;
    q("#notebook-status").classList.toggle("is-error", error);
  };
  const date = (iso) => {
    if (!iso || !Number.isFinite(new Date(iso).getTime())) return "";
    return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" }).format(new Date(iso));
  };
  const request = (path, options = {}) => api(`/notebooks${path}`, options);

  function renderLayout() {
    const current = !!model.current;
    const hasMaterials = model.materials.length > 0;
    const workspace = q(".notebook-workspace");
    workspace.classList.toggle("is-reading", current);
    workspace.classList.toggle("is-compose", !current);
    workspace.classList.toggle("is-empty", !hasMaterials && !model.notebooks.length);
    q("#notebook-composer").hidden = current;
    q("#notebook-document").hidden = !current;
    q(".notebook-studio").hidden = !current;
    q("#notebook-quickstart").hidden = hasMaterials && model.selected.size > 0;
    q("#notebook-form").hidden = !hasMaterials;
    q("#notebook-generate").disabled = !model.selected.size || model.generating;
    q("#notebook-new").disabled = model.generating;
    q("#notebook-form").setAttribute("aria-busy", String(model.generating));
    q("#notebook-composer-title").textContent = model.preparing?.course ? "Подготовка: " + model.preparing.course : hasMaterials ? model.selected.size ? "Материал выбран. Можно начинать." : "Выбери, к чему готовиться" : "Добавь лекцию — получи конспект";
    q("#notebook-selection-hint").textContent = !model.selected.size && hasMaterials ? "Выбери материал слева или добавь нужную лекцию." : hasMaterials ? "Соберём главное и вопросы для самопроверки. Дополнительные настройки не обязательны." : "Загрузить файл или вставить текст — больше ничего обязательного.";
  }

  async function load() {
    if (model.pending) return model.pending;
    model.pending = (async () => {
      status("Открываем твои источники…");
      try {
        const [workspace, result] = await Promise.all([api("/workspace"), request("")]);
        const previousIds = new Set(model.materials.map((material) => material.id));
        model.materials = workspace.materials || [];
        model.notebooks = result.notebooks || [];
        if (model.current && !model.notebooks.some((item) => item.id === model.current.id)) model.current = null;
        if (!model.current && !model.preparing && !model.userRequestedNew && model.notebooks.length) {
          model.current = await request(`/${encodeURIComponent(model.notebooks[0].id)}`);
          model.selected = new Set(model.current.material_ids || []);
        }
        if (!model.initialized) {
          if (!model.current && !model.preparing) model.materials.forEach((material) => model.selected.add(material.id));
          model.initialized = true;
        } else model.materials.filter((material) => !previousIds.has(material.id)).forEach((material) => model.selected.add(material.id));
        const allowed = new Set(model.materials.map((material) => material.id));
        model.selected = new Set([...model.selected].filter((id) => allowed.has(id)));
        renderSources();
        renderSaved();
        renderDocument();
        status();
      } catch (error) {
        status(error.message, true);
        if (!q("#notebook-document").children.length) renderDocument();
      } finally {
        model.pending = null;
        if (!model.restoring) window.CampusNavigation?.checkpoint();
      }
    })();
    return model.pending;
  }

  function renderSources() {
    const area = q("#notebook-source-list");
    area.replaceChildren();
    q("#notebook-source-count").textContent = `${model.selected.size}/${model.materials.length}`;
    if (!model.materials.length) area.append(make("p", "notebook-caption", "Добавь PDF или конспект. Источники сохранятся и будут доступны для новых заметок."));
    for (const material of model.materials) {
      const label = make("label", "notebook-source-item");
      const check = make("input");
      check.type = "checkbox";
      check.checked = model.selected.has(material.id);
      check.disabled = model.generating;
      check.addEventListener("change", () => {
        if (check.checked) model.selected.add(material.id);
        else model.selected.delete(material.id);
        q("#notebook-source-count").textContent = `${model.selected.size}/${model.materials.length}`;
        renderLayout();
        window.CampusNavigation?.checkpoint();
      });
      const copy = make("span");
      copy.append(make("strong", "", material.name), make("small", "", `${material.page_count} стр. · ${date(material.uploaded_at)}`));
      label.append(check, copy);
      area.append(label);
    }
    renderLayout();
  }

  function renderSaved() {
    const area = q("#notebook-saved-list");
    q("#notebook-saved-count").textContent = model.notebooks.length || "";
    area.replaceChildren();
    if (!model.notebooks.length) area.append(make("p", "notebook-caption", "Сохранённые конспекты появятся здесь."));
    for (const item of model.notebooks) {
      const button = click("", async () => {
        if (model.generating) { toast("Конспект ещё готовится. Дождись результата."); return; }
        await showView("notebook", { context:{mode:"read", note_id:item.id, preparing:null} });
      }, "notebook-saved-item" + (model.current?.id === item.id ? " is-active" : ""));
      button.append(make("span", "", item.title || "Конспект"), make("small", "", `${date(item.created_at)}${item.source_count != null ? ` · ${item.source_count} цитат` : ""}`));
      area.append(button);
    }
  }

  function citationButtons(ids, note = model.current) {
    const fragment = document.createDocumentFragment();
    for (const id of ids || []) {
      const index = (note?.sources || []).findIndex((source) => String(source.id) === String(id));
      if (index < 0) continue;
      const source = note.sources[index];
      const button = click(index + 1, () => showCitation(source), "notebook-citation");
      button.title = `${source.file}, страница ${source.page}`;
      button.setAttribute("aria-label", `Проверить источник ${index + 1}: ${source.file}, страница ${source.page}`);
      fragment.append(button);
    }
    return fragment;
  }

  async function showCitation(source) {
    q("#material-name").textContent = `${source.file} · страница ${source.page}${source.line ? ` · строка ${source.line}` : ""}`;
    const content = q("#material-content");
    content.replaceChildren(make("p", "muted", "Цитата, на которую опирается конспект:"), make("blockquote", "notebook-source-quote", source.quote));
    content.append(click("Открыть текст всей страницы ↓", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const material = await api(`/materials/${encodeURIComponent(source.material_id)}`);
        const page = (material.pages || []).find((item) => Number(item.page) === Number(source.page));
        if (!page) throw new Error("Страница больше не доступна. Цитата сохранена в конспекте.");
        const section = make("section");
        section.append(make("h3", "", "Полная страница источника"));
        page.text.split("\n").forEach((line, index) => section.append(make("pre", index + 1 === Number(source.line) ? "cited-line" : "source-line", `${index + 1} │ ${line}`)));
        content.append(section);
        button.remove();
      } catch (error) {
        content.append(make("p", "academic-error", error.message));
        button.disabled = false;
      }
    }));
    q("#material-dialog").showModal();
  }

  function emptyPanel(title, description) {
    const empty = make("div", "notebook-empty");
    empty.append(make("div", "notebook-empty-mark", "▤"), make("h3", "", title), make("p", "", description));
    return empty;
  }

  function renderDocument() {
    const area = q("#notebook-document");
    const tools = q("#notebook-study-tools");
    area.replaceChildren();
    tools.replaceChildren();
    const note = model.current;
    renderLayout();
    if (!note) return;
    const header = make("div", "notebook-doc-heading");
    const title = make("div");
    title.append(make("span", "notebook-mode", "Конспект из ваших материалов"), make("h2", "", note.title || "Учебный конспект"), make("div", "notebook-doc-date", `${date(note.created_at)} · ${note.material_ids?.length || 0} материалов`));
    header.append(title, make("span", "notebook-small-symbol", "▤"));
    area.append(header);
    const downloads = make("div", "notebook-downloads");
    const otherFormats = make("details", "notebook-other-formats");
    otherFormats.append(make("summary", "", "Другие форматы"));
    for (const [format, label] of [["pdf", "↓ PDF"], ["md", "↓ Markdown"], ["txt", "↓ Текст"], ["html", "↓ HTML"]]) {
      const link = make("a", "button secondary", label);
      link.href = `/api/notebooks/${encodeURIComponent(note.id)}/export?format=${format}`;
      if (format === "pdf") downloads.append(link);
      else otherFormats.append(link);
    }
    downloads.append(otherFormats);
    area.append(downloads);
    const method = make("details", "notebook-method");
    method.append(make("summary", "", "Как подготовлен конспект"), make("p", "", note.method_note || (note.mode === "gemini" ? "Сформировано Gemini на основе выбранных источников. Проверяй ключевые утверждения по цитатам." : "Собрано из цитат выбранных материалов без генерации ИИ. Все фрагменты можно проверить по ссылкам.")));
    area.append(method);
    if (note.ai_warning) area.append(make("p", "notebook-ai-warning", note.ai_warning));
    for (const section of note.sections || []) {
      const block = make("section", "notebook-section");
      block.append(make("h3", "", section.title));
      for (const paragraph of section.paragraphs || []) {
        const text = make("p", "", paragraph.text);
        text.append(citationButtons(paragraph.source_ids, note));
        block.append(text);
      }
      area.append(block);
    }
    if (!note.sections?.length) area.append(make("p", "notebook-caption", "В документе нет текстовых разделов. Проверь карточки и исходные цитаты справа."));
    const sources = make("details", "academic-details-source");
    sources.append(make("summary", "", `Все источники и цитаты · ${note.sources?.length || 0}`));
    (note.sources || []).forEach((source, index) => {
      const row = make("div", "notebook-source-reference");
      row.append(click(`[${index + 1}] ${source.file} · стр. ${source.page}`, () => showCitation(source)));
      sources.append(row);
    });
    area.append(sources);
    const footer = make("div", "notebook-document-footer");
    footer.append(click("＋ Собрать новый конспект", reset), click("Удалить конспект", async () => {
      if (!(await confirmAction("Удалить этот конспект?", "Источники останутся в материалах. Удалится только собранный конспект."))) return;
      try {
        await request(`/${encodeURIComponent(note.id)}`, {method:"DELETE"});
        await showView("notebook", {history:"replace", context:{mode:"compose", selected:[...model.selected], preparing:null}});
        toast("Конспект удалён. Исходные материалы сохранены.");
      } catch (error) { status(error.message, true); }
    }));
    area.append(footer);
    renderStudyTools(note);
  }

  function renderStudyTools(note) {
    const tools = q("#notebook-study-tools");
    tools.replaceChildren();
    const group = (title, entries, render, noun) => {
      if (!entries?.length) return;
      const section = make("section", "notebook-studio-group");
      section.append(make("h3", "", title));
      entries.slice(0, 3).forEach((entry, index) => section.append(render(entry, index)));
      if (entries.length > 3) {
        const more = make("details", "notebook-more");
        more.append(make("summary", "", "Ещё " + (entries.length - 3) + " " + noun));
        entries.slice(3).forEach((entry, index) => more.append(render(entry, index + 3)));
        section.append(more);
      }
      tools.append(section);
    };
    group("Главные понятия", note.key_terms, (term) => {
      const card = make("div", "notebook-term");
      const text = make("p", "", term.definition);
      text.append(citationButtons(term.source_ids, note));
      card.append(make("strong", "", term.term), text);
      return card;
    }, "понятий");
    group("Ответишь без подсказки?", note.questions, (question, index) => {
      const card = make("details", "notebook-question");
      card.append(make("summary", "", (index + 1) + ". " + question.question));
      const answer = make("p", "", question.answer);
      answer.append(citationButtons(question.source_ids, note));
      card.append(answer);
      return card;
    }, "вопросов");
    if (!note.key_terms?.length && !note.questions?.length) tools.append(make("p", "notebook-caption", "Для повторения используй главное из конспекта. Определений для карточек в материале пока нет."));
    tools.append(click("Открыть тренировку →", () => {
      showView("practice");
      selectPractice("quests");
      const materialId = note.material_ids?.find((id) => model.materials.some((material) => material.id === id));
      if (materialId) {
        q("#quest-material").value = materialId;
        q("#quest-source-form").requestSubmit();
      }
    }));
    if (window.matchMedia("(max-width: 600px)").matches) {
      q("#notebook-source-fold").open = false;
      q("#notebook-tools-fold").open = true;
    }
  }

  function reset() {
    if (model.generating) { toast("Конспект ещё готовится. Дождись результата."); return; }
    return showView("notebook", {context:{mode:"compose", selected:[...model.selected], preparing:null}});
  }

  q("#notebook-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (model.generating) return;
    const submit = q("#notebook-generate");
    if (!model.selected.size) { status("Выбери хотя бы один источник слева или загрузи PDF / текстовый конспект.", true); return; }
    const payload = {title:q("#notebook-title").value.trim() || undefined, focus:q("#notebook-focus").value.trim() || undefined, style:q('input[name="notebook-style"]:checked').value, material_ids:[...model.selected]};
    const generationOrigin = JSON.stringify(navigationState());
    model.generating = true;
    renderSources();
    submit.disabled = true;
    submit.textContent = "Собираем конспект и проверяем источники…";
    status("Собираем конспект из выбранных материалов…");
    let bindingWarning = "";
    try {
      if (model.preparing?.course_id) {
        try {
          await api(`/academic/courses/${encodeURIComponent(model.preparing.course_id)}/materials`, {method:"PATCH", body:JSON.stringify({material_ids:payload.material_ids})});
        } catch (error) { bindingWarning = "Конспект подготовлен, но связать материалы с предметом не удалось: " + error.message; }
      }
      const result = await request("", {method:"POST", body:JSON.stringify(payload)});
      if (state.view === "notebook" && JSON.stringify(navigationState()) === generationOrigin)
        await showView("notebook", {context:{mode:"read", note_id:result.id, preparing:model.preparing}});
      else await load();
      status(bindingWarning);
      toast("Конспект сохранён. Его можно скачать и открыть позже.");
    } catch (error) { status(error.message, true); }
    finally { model.generating = false; submit.textContent = "Подготовить конспект →"; renderSources(); renderLayout(); }
  });

  q("#notebook-upload").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    event.target.disabled = true;
    status("Читаем источник…");
    try {
      const form = new FormData();
      form.append("file", file);
      const material = await api("/materials", {method:"POST", body:form});
      model.selected.add(material.id);
      await refresh();
      await load();
      status();
      toast("Источник добавлен и выбран для конспекта.");
    } catch (error) { status(error.message, true); }
    finally { event.target.disabled = false; event.target.value = ""; }
  });
  q("#notebook-new").addEventListener("click", reset);
  q("#notebook-quick-paste").addEventListener("click", () => q("#notebook-paste").click());
  q("#notebook-paste").addEventListener("click", () => {
    const dialog = q("#material-note-dialog");
    dialog.addEventListener("close", () => load(), {once:true});
    openNoteDialog();
  });
  async function prepare(options = {}) {
    if (model.generating) { toast("Первый конспект ещё готовится. Дождись результата, затем выбери другой предмет."); return; }
    return showView("notebook", {context:{mode:"prepare", options}});
  }

  function navigationState() {
    if (!model.initialized) return null;
    return {
      mode:model.current ? "read" : "compose", note_id:model.current?.id || null,
      selected:[...model.selected], preparing:model.preparing,
      title:q("#notebook-title").value, focus:q("#notebook-focus").value,
      style:q('input[name="notebook-style"]:checked')?.value || "summary",
    };
  }

  async function openPreparation(options, version) {
    model.preparing = options;
    await load();
    if (version !== model.restoreVersion) return;
    const allowed = new Set(model.materials.map((item) => item.id));
    let chosen = (options.material_ids || []).filter((id) => allowed.has(id));
    if (!chosen.length && options.course) {
      const words = options.course.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter((word) => word.length > 3 && !["пример", "учебный"].includes(word));
      const matches = model.materials.map((item) => ({item, score:words.filter((word) => item.name.toLowerCase().includes(word)).length}));
      const best = Math.max(0, ...matches.map((item) => item.score));
      chosen = best ? matches.filter((item) => item.score === best).map((item) => item.item.id) : [];
    }
    model.selected = new Set(chosen);
    const saved = chosen.length ? model.notebooks.find((item) => item.material_ids?.length === chosen.length && item.material_ids.every((id) => model.selected.has(id))) : null;
    model.current = null;
    if (saved) {
      try {
        const note = await request(`/${encodeURIComponent(saved.id)}`);
        if (version !== model.restoreVersion) return;
        model.current = note;
      }
      catch (_) { status("Сохранённый конспект недоступен. Можно подготовить новый."); }
    }
    q("#notebook-form").reset();
    q("#notebook-title").value = options.course ? "Подготовка: " + options.course : "";
    q("#notebook-focus").value = (options.focus || "").slice(0, 300);
    q('input[name="notebook-style"][value="exam"]').checked = true;
    q("#notebook-options").open = false;
    renderSources();
    renderSaved();
    renderDocument();
    if (!chosen.length) status("Добавь лекцию по этому предмету или выбери подходящий материал.");
  }

  async function restoreNavigation(context) {
    const version = ++model.restoreVersion;
    model.restoring = true;
    model.userRequestedNew = true;
    try {
      if (context.mode === "prepare") return await openPreparation(context.options || {}, version);
      model.preparing = context.preparing || null;
      await load();
      if (version !== model.restoreVersion) return;
      let note = null;
      if (context.mode === "read" && context.note_id) {
        try { note = await request(`/${encodeURIComponent(context.note_id)}`); }
        catch (_) { status("Этот конспект больше не доступен. Источники можно выбрать заново."); }
      }
      if (version !== model.restoreVersion) return;
      model.current = note;
      model.userRequestedNew = !note;
      const allowed = new Set(model.materials.map((item) => item.id));
      model.selected = new Set((note?.material_ids || context.selected || []).filter((id) => allowed.has(id)));
      q("#notebook-form").reset();
      q("#notebook-title").value = context.title || "";
      q("#notebook-focus").value = context.focus || "";
      const style = ["summary", "exam", "flashcards"].includes(context.style) ? context.style : "summary";
      q(`input[name="notebook-style"][value="${style}"]`).checked = true;
      q("#notebook-options").open = false;
      renderSources(); renderSaved(); renderDocument();
    } finally {
      if (version === model.restoreVersion) {
        model.restoring = false;
        window.CampusNavigation?.checkpoint();
      }
    }
  }
  q("#notebook-form").addEventListener("input", () => window.CampusNavigation?.checkpoint());
  window.CampusNotebook = { load, prepare, navigationState, restoreNavigation };
})();
