/* =========================================================================
   СКРИПТ СТРАНИЦЫ «ГЕНЕРАТОР ПОСТОВ»
   Отвечает за:
     1. Переключение режимов «Шаблон» / «Нейросеть».
     2. Проверку обязательных полей (описание — для шаблона, ссылка — для AI).
     3. Отправку формы (POST /generate или POST /generate-ai) и показ поста.
     4. Копирование поста в буфер обмена с подсказкой «Пост скопирован».
   ========================================================================= */

/* ------------------------------------------------------------------
   Находим элементы страницы, с которыми будем работать.
------------------------------------------------------------------ */
const form             = document.getElementById("post-form");
const descriptionInput = document.getElementById("description");
const descriptionError = document.getElementById("description-error");
const linkInput        = document.getElementById("link");
const linkError        = document.getElementById("link-error");
const resultSection    = document.getElementById("result-section");
const postOutput       = document.getElementById("post-output");
const copyButton       = document.getElementById("copy-btn");
const copyFeedback     = document.getElementById("copy-feedback");

/* Кнопки переключателя и группы полей, связанные с режимами */
const modeButtons       = document.querySelectorAll(".mode-btn[data-mode]");
const templateGroup     = document.getElementById("template-group");
const aiGroup           = document.getElementById("ai-group");
const batchGroup        = document.getElementById("batch-group");
const generateButton    = document.getElementById("generate-btn");
const moodField         = document.getElementById("mood").closest(".field");

/* Текущий режим: "template", "ai" или "batch" */
let currentMode = "template";

/* ------------------------------------------------------------------
    ПОКАЗ / СКРЫТИЕ ОШИБКИ ПОД ПОЛЕМ.
    input    — поле, у которого подсвечиваем рамку;
    errorEl  — элемент с текстом ошибки;
    show     — true, значит ошибку нужно показать.
------------------------------------------------------------------ */
function toggleError(input, errorEl, show) {
    errorEl.hidden = !show;
    const field = input.closest(".field");
    if (show) field.classList.add("invalid");
    else field.classList.remove("invalid");
}

/* ------------------------------------------------------------------
    ПЕРЕКЛЮЧЕНИЕ РЕЖИМОВ.
    Показываем нужные поля и запоминаем активный режим.
------------------------------------------------------------------ */
function setMode(mode) {
    currentMode = mode;

    // Подсвечиваем активную кнопку переключателя.
    modeButtons.forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.mode === mode);
    });

    // Показываем поля только нужного режима.
    templateGroup.hidden = (mode !== "template");
    aiGroup.hidden       = (mode !== "ai");
    batchGroup.hidden    = (mode !== "batch");

    // В пакетном режиме своя кнопка и своё настроение — прячем общие.
    generateButton.hidden = (mode === "batch");
    moodField.hidden      = (mode === "batch");

    // Сбрасываем ошибки при смене режима.
    toggleError(descriptionInput, descriptionError, false);
    toggleError(linkInput, linkError, false);
    toggleError(
        document.getElementById("batch-input"),
        document.getElementById("batch-input-error"),
        false,
    );
}

// Навешиваем обработчики на кнопки переключателя.
modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
});

/* ------------------------------------------------------------------
   ВАЛИДАЦИЯ ПЕРЕД ОТПРАВКОЙ.
   В режиме «Шаблон» обязательно описание, в режиме «Нейросеть» — ссылка.
   Возвращает true, если всё заполнено.
------------------------------------------------------------------ */
function validateForm() {
    if (currentMode === "template") {
        const hasDescription = descriptionInput.value.trim().length > 0;
        toggleError(descriptionInput, descriptionError, !hasDescription);
        return hasDescription;
    }

    const hasLink = linkInput.value.trim().length > 0;
    toggleError(linkInput, linkError, !hasLink);
    return hasLink;
}

/* ------------------------------------------------------------------
   ОБРАБОТКА ОТПРАВКИ ФОРМЫ.
   Не даём странице перезагрузиться, отправляем данные на сервер
   и показываем сгенерированный пост.
------------------------------------------------------------------ */
form.addEventListener("submit", async (event) => {
    event.preventDefault(); // отключаем стандартную перезагрузку страницы

    // В пакетном режиме у своя кнопка «Проверить список».
    if (currentMode === "batch") return;

    // Проверяем обязательное поле текущего режима.
    if (!validateForm()) return;

    // В режиме нейросети отправляем ссылку и выбранное настроение —
    // всё остальное нейросеть придумает сама по содержимому страницы.
    const isAI = (currentMode === "ai");
    const payload = isAI
        ? { link: linkInput.value.trim(), mood: form.mood.value }
        : {
            name:        form.name.value.trim(),
            description: descriptionInput.value.trim(),
            benefit:     form.benefit.value.trim(),
            mood:        form.mood.value,
            name_case:   document.getElementById("name-case").value,
          };

    const endpoint = isAI ? "/generate-ai" : "/generate";
    const busyText = isAI ? "Нейросеть думает…" : "Формирую...";

    // Инициализируем кнопку — чтобы не было двойных кликов.
    const button = document.getElementById("generate-btn");
    button.disabled = true;
    button.textContent = busyText;

    try {
        // Отправляем POST-запрос на сервер (см. app.py).
        const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        // Превращаем ответ в объект.
        const data = await response.json();

        // Сервер мог вернуть ошибку (пустое поле, недоступная ссылка, нет ключа).
        if (!response.ok) {
            throw new Error(data.error || "Что-то пошло не так");
        }

        // Всё хорошо — показываем пост.
        postOutput.textContent = data.post;
        resultSection.hidden = false;
        updateFade(postOutput);

        // Запоминаем данные последней генерации — чтобы сохранить пост целиком.
        lastPost = isAI
            ? { name: linkInput.value.trim(), text: data.post, mood: form.mood.value, mode: "ai" }
            : {
                name:        form.name.value.trim(),
                text:        data.post,
                mood:        form.mood.value,
                mode:        "template",
              };

        // Новый пост ещё не сохранён — снова доступна кнопка «Сохранить».
        savedPostId = null;
        saveButton.disabled = false;
        saveButton.textContent = "Сохранить пост";
        saveFeedback.hidden = true;

        // Сброс хештегов — под новой пост они свои.
        currentHashtags = [];
        tagsBox.hidden = true;
        hashtagsSource.hidden = true;

        // Сбрасываем сообщение «Пост скопирован» для нового поста.
        copyFeedback.hidden = true;
    } catch (error) {
        // Показываем тексты ошибки под обязательным полем текущего режима.
        const target = isAI ? linkInput : descriptionInput;
        const targetError = isAI ? linkError : descriptionError;
        targetError.textContent = error.message || "Что-то пошло не так";
        toggleError(target, targetError, true);
        console.error(error);
    } finally {
        // Возвращаем кнопку в обычное состояние.
        button.disabled = false;
        button.textContent = "Сформировать пост";
    }
});

/* =========================================================================
   ПОДБОР ХЕШТЕГОВ
   ========================================================================= */
const hashtagsButton = document.getElementById("hashtags-btn");
const hashtagsSource = document.getElementById("hashtags-source");
const tagsBox        = document.getElementById("tags-box");
const tagsList       = document.getElementById("tags");
const tagsCount      = document.getElementById("tags-count");
const tagsCopy       = document.getElementById("tags-copy");
const tagsClear      = document.getElementById("tags-clear");

const MAX_TAGS = 30;

/* Теги текущего (ещё не сохранённого) поста */
let currentHashtags = [];

/* Отрисовка чипов. interactive=false — статичные теги в карточке поста. */
function renderTags(tags, interactive = true) {
    tagsList.innerHTML = "";

    tags.forEach((tag) => {
        const chip = document.createElement(interactive ? "button" : "span");
        chip.type = "button";
        chip.className = interactive ? "tag" : "tag tag-static";
        chip.textContent = "#" + tag;

        if (interactive) {
            chip.title = "Убрать тег";
            chip.addEventListener("click", () => {
                currentHashtags = currentHashtags.filter((item) => item !== tag);
                renderTags(currentHashtags);
            });
        }

        tagsList.appendChild(chip);
    });

    tagsBox.hidden = tags.length === 0;
    tagsCount.textContent = `${tags.length} из ${MAX_TAGS}`;
}

/* Показывает 3 «скелетона», пока идёт подбор */
function showTagSkeleton() {
    tagsList.innerHTML = "";
    for (let i = 0; i < 3; i++) {
        const skeleton = document.createElement("span");
        skeleton.className = "tag loading";
        skeleton.textContent = "загрузка";
        tagsList.appendChild(skeleton);
    }
    tagsBox.hidden = false;
    tagsCount.textContent = "подбираю…";
}

hashtagsButton.addEventListener("click", async () => {
    const text = (lastPost && lastPost.text) || postOutput.textContent;
    if (!text.trim()) {
        showToast("Сначала сгенерируй пост", true);
        return;
    }

    hashtagsButton.disabled = true;
    hashtagsButton.textContent = "Подбираю…";
    showTagSkeleton();

    try {
        const data = await api("/api/hashtags", "POST", {
            text,
            mood: (lastPost && lastPost.mood) || form.mood.value,
        });

        currentHashtags = data.hashtags || [];
        renderTags(currentHashtags);

        hashtagsSource.hidden = false;
        hashtagsSource.textContent = data.source === "ai"
            ? "подобрала нейросеть"
            : "офлайн-подбор (без нейросети)";
    } catch (error) {
        tagsBox.hidden = true;
        showToast("Не удалось подобрать хештеги: " + error.message, true);
    } finally {
        hashtagsButton.disabled = false;
        hashtagsButton.textContent = "Подобрать хештеги";
    }
});

/* Скопировать все теги одной строкой */
tagsCopy.addEventListener("click", async () => {
    if (!currentHashtags.length) return;
    await copyToClipboard(currentHashtags.map((tag) => "#" + tag).join(" "));
    showToast("Хештеги скопированы");
});

/* Очистить подбор */
tagsClear.addEventListener("click", () => {
    currentHashtags = [];
    renderTags(currentHashtags);
    tagsBox.hidden = true;
});

/* =========================================================================
   ХРАНИЛИЩЕ ПОСТОВ: «Мои посты» — сохранение, редактирование, удаление
   ========================================================================= */

/* Элементы секции «Мои посты» */
const saveButton    = document.getElementById("save-btn");
const saveFeedback  = document.getElementById("save-feedback");
const postsSection  = document.getElementById("posts-section");
const postsList     = document.getElementById("posts-list");
const postsEmpty    = document.getElementById("posts-empty");
const postsCounter  = document.getElementById("posts-counter");

/* Модалка подтверждения */
const modalOverlay  = document.getElementById("modal-overlay");
const modalTitle    = document.getElementById("modal-title");
const modalText     = document.getElementById("modal-text");
const modalExtra    = document.getElementById("modal-extra");
const modalCancel   = document.getElementById("modal-cancel");
const modalConfirm  = document.getElementById("modal-confirm");

/* Тост */
const toastElement  = document.getElementById("toast");

/* Данные последней генерации (для кнопки «Сохранить пост») */
let lastPost = null;
let savedPostId = null;

/* Кэш постов с сервера — для редактирования и удаления */
let postsCache = [];

/* ------------------------------------------------------------------
   ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
------------------------------------------------------------------ */
/* Универсальный fetch: кидает Error с текстом сообщения с сервера. */
async function api(url, method = "GET", body = null) {
    const response = await fetch(url, {
        method,
        headers: body ? { "Content-Type": "application/json" } : {},
        body: body ? JSON.stringify(body) : undefined,
    });

    let data = null;
    try { data = await response.json(); } catch { /* не JSON — оставляем null */ }

    if (!response.ok) {
        throw new Error((data && data.error) || "Что-то пошло не так");
    }
    return data || {};
}

/* Всплывающее сообщение внизу экрана. */
let toastTimer = null;
function showToast(message, isError = false) {
    toastElement.textContent = message;
    toastElement.classList.toggle("error", isError);
    toastElement.hidden = false;

    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastElement.hidden = true; }, 3000);
}

/* Копирование произвольного текста в буфер. */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
    }
}

/* Дата в читаемом виде: 07.10.2026, 14:30 */
function formatDate(iso) {
    try {
        return new Date(iso).toLocaleString("ru-RU", {
            day: "2-digit", month: "2-digit", year: "numeric",
            hour: "2-digit", minute: "2-digit",
        });
    } catch {
        return iso || "";
    }
}

/* Настроение → подпись для бейджа */
const MOOD_LABELS = {
    "яркий": "яркий",
    "деловой": "деловой",
    "дружелюбный": "дружелюбный",
};

/* ------------------------------------------------------------------
   МОДАЛЬНОЕ ОКНО ПОДТВЕРЖДЕНИЯ
   openModal(...) показывает окно, onConfirm вызывается по кнопке подтверждения.
   Возвращает промис: true — пользователь согласился, false — отменил.
------------------------------------------------------------------ */
let modalResolve = null;
let modalPrevFocus = null;      // куда вернуть фокус после закрытия

function openModal({
    title,
    text,
    confirmLabel = "Подтвердить",
    cancelLabel = "Отмена",
    danger = true,
    buildExtra = null,        // колбэк: наполняет блок modalExtra своим контентом
}) {
    modalTitle.textContent = title;
    modalText.textContent = text;
    modalConfirm.textContent = confirmLabel;
    modalCancel.textContent = cancelLabel;
    modalConfirm.className = danger ? "btn-danger" : "btn-small confirm";

    modalExtra.innerHTML = "";
    modalExtra.hidden = !buildExtra;
    if (buildExtra) buildExtra(modalExtra);

    modalPrevFocus = document.activeElement;
    modalOverlay.hidden = false;
    modalConfirm.focus();

    return new Promise((resolve) => { modalResolve = resolve; });
}

function closeModal(result) {
    modalOverlay.hidden = true;
    if (modalPrevFocus instanceof HTMLElement) modalPrevFocus.focus();
    modalPrevFocus = null;
    if (modalResolve) {
        modalResolve(result);
        modalResolve = null;
    }
}

modalCancel.addEventListener("click", () => closeModal(false));
modalConfirm.addEventListener("click", () => closeModal(true));
modalOverlay.addEventListener("click", (event) => {
    if (event.target === modalOverlay) closeModal(false);
});
document.addEventListener("keydown", (event) => {
    if (modalOverlay.hidden) return;

    if (event.key === "Escape") {
        closeModal(false);
        return;
    }

    // Tab не уходит за пределы модалки
    if (event.key === "Tab") {
        const focusables = modalOverlay.querySelectorAll(
            "button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex='-1'])"
        );
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }
});

/* ------------------------------------------------------------------
   ГРАДИЕНТ-ВЫЦВЕТАНИЕ У ПРЕВЬЮ С ПРОКРУТКОЙ
   Пока текст не долистан — снизу видно затухание («продолжение есть»).
------------------------------------------------------------------ */
function updateFade(el) {
    const hasMore = el.scrollHeight - el.scrollTop - el.clientHeight > 4;
    el.classList.toggle("scroll-fade", hasMore);
}

function refreshFades(root = document) {
    root.querySelectorAll(".post-output, .post-card-text").forEach(updateFade);
}

// scroll не всплывает — слушаем на фазе перехвата
document.addEventListener("scroll", (event) => {
    const el = event.target;
    if (el instanceof Element &&
        (el.classList.contains("post-output") || el.classList.contains("post-card-text"))) {
        updateFade(el);
    }
}, true);

/* ------------------------------------------------------------------
   ОТРИСОВКА СПИСКА ПОСТОВ
------------------------------------------------------------------ */
function renderPosts() {
    postsList.innerHTML = "";

    const hasPosts = postsCache.length > 0;
    postsEmpty.hidden = hasPosts;
    postsCounter.hidden = !hasPosts;
    postsCounter.textContent = postsCache.length === 1
        ? "1 пост"
        : `${postsCache.length} постов`;

    postsCache.forEach((post) => postsList.appendChild(createPostCard(post)));
    refreshFades();
}

/* Карточка одного поста. Текст и имя вставляем через textContent —
   это защита от вставки разметки из данных. */
function createPostCard(post) {
    const card = document.createElement("article");
    card.className = "post-card";
    card.dataset.id = post.id;

    /* --- Шапка: название + бейджи --- */
    const head = document.createElement("div");
    head.className = "post-card-head";

    const title = document.createElement("h3");
    title.className = "post-card-title";
    title.textContent = post.name || "Без названия";
    head.appendChild(title);

    if (post.mood && MOOD_LABELS[post.mood]) {
        const mood = document.createElement("span");
        mood.className = "badge badge-mood";
        mood.textContent = MOOD_LABELS[post.mood];
        head.appendChild(mood);
    }

    const date = document.createElement("span");
    date.className = "badge";
    date.textContent = formatDate(post.updated_at || post.created_at);
    head.appendChild(date);

    const chars = document.createElement("span");
    chars.className = "badge";
    chars.textContent = `${(post.text || "").length} знаков`;
    head.appendChild(chars);

    /* --- Текст (превью или поле редактирования) --- */
    const text = document.createElement("div");
    text.className = "post-card-text";
    text.textContent = post.text || "";

    /* --- Сохранённые хештеги (только показ) --- */
    let tagsBlock = null;
    if (Array.isArray(post.hashtags) && post.hashtags.length) {
        tagsBlock = document.createElement("div");
        tagsBlock.className = "tags";
        post.hashtags.forEach((tag) => {
            const chip = document.createElement("span");
            chip.className = "tag tag-static";
            chip.textContent = "#" + tag;
            tagsBlock.appendChild(chip);
        });
    }

    /* --- Действия --- */
    const actions = document.createElement("div");
    actions.className = "post-card-actions";

    const btnEdit = makeButton("Редактировать", "js-edit");
    const btnCopy = makeButton("Копировать", "js-copy");
    const btnDelete = makeButton("Удалить", "js-delete danger");
    const btnSave = makeButton("Сохранить", "js-save confirm");
    const btnCancel = makeButton("Отмена", "js-cancel");
    btnSave.hidden = true;
    btnCancel.hidden = true;

    actions.append(btnEdit, btnCopy, btnDelete, btnSave, btnCancel);

    if (tagsBlock) card.append(head, text, tagsBlock, actions);
    else card.append(head, text, actions);
    return card;
}

function makeButton(label, classes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-small " + classes;
    button.textContent = label;
    return button;
}

/* ------------------------------------------------------------------
   ЗАГРУЗКА СПИСКА С СЕРВЕРА
------------------------------------------------------------------ */
async function loadPosts() {
    try {
        const data = await api("/api/posts");
        postsCache = Array.isArray(data.posts) ? data.posts : [];
        renderPosts();
    } catch (error) {
        showToast("Не удалось загрузить посты: " + error.message, true);
    }
}

/* ------------------------------------------------------------------
   СОХРАНЕНИЕ ТОЛЬКО ЧТО СГЕНЕРИРОВАННОГО ПОСТА
------------------------------------------------------------------ */
saveButton.addEventListener("click", async () => {
    if (!lastPost) {
        showToast("Сначала сгенерируй пост", true);
        return;
    }

    saveButton.disabled = true;
    saveButton.textContent = "Сохраняю…";

    // Теги текущего подбора уходят вместе с постом.
    const payload = Object.assign({}, lastPost, { hashtags: currentHashtags });

    try {
        const data = await api("/api/posts", "POST", payload);
        savedPostId = data.post.id;

        saveButton.textContent = "Пост сохранён";
        saveFeedback.hidden = false;
        showToast("Пост сохранён в «Мои посты»");

        await loadPosts();
        postsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
        saveButton.disabled = false;
        saveButton.textContent = "Сохранить пост";
        showToast("Не удалось сохранить: " + error.message, true);
    }
});

/* ------------------------------------------------------------------
   ДЕЙСТВИЯ В КАРТОЧКЕ (делегирование событий на список)
------------------------------------------------------------------ */
postsList.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;

    const card = button.closest(".post-card");
    if (!card) return;

    const post = postsCache.find((item) => item.id === card.dataset.id);
    if (!post) return;

    /* --- Копировать --- */
    if (button.classList.contains("js-copy")) {
        await copyToClipboard(post.text || "");
        showToast("Пост скопирован");
        return;
    }

    /* --- Редактировать --- */
    if (button.classList.contains("js-edit")) {
        enterEditMode(card);
        return;
    }

    /* --- Отмена редактирования --- */
    if (button.classList.contains("js-cancel")) {
        renderPosts();
        return;
    }

    /* --- Сохранить правку --- */
    if (button.classList.contains("js-save")) {
        const textarea = card.querySelector(".post-card-edit");
        const newText = (textarea ? textarea.value : "").trim();

        if (!newText) {
            showToast("Текст поста не может быть пустым", true);
            return;
        }
        if (newText.length > 5000) {
            showToast("Текст длиннее 5000 знаков", true);
            return;
        }

        button.disabled = true;
        button.textContent = "Сохраняю…";

        try {
            await api(`/api/posts/${post.id}`, "PUT", { text: newText });
            showToast("Изменения сохранены");
            await loadPosts();
        } catch (error) {
            button.disabled = false;
            button.textContent = "Сохранить";
            showToast("Не удалось сохранить: " + error.message, true);
        }
        return;
    }

    /* --- Удалить --- */
    if (button.classList.contains("js-delete")) {
        const confirmed = await openModal({
            title: "Удалить пост?",
            text: `«${post.name || "Без названия"}» будет удалён навсегда. Отменить это действие нельзя.`,
            confirmLabel: "Удалить",
        });
        if (!confirmed) return;

        try {
            await api(`/api/posts/${post.id}`, "DELETE");
            showToast("Пост удалён");
            await loadPosts();
        } catch (error) {
            showToast("Не удалось удалить: " + error.message, true);
        }
    }
});

/* Переводит карточку в режим редактирования: превью → textarea,
   кнопки «Редактировать/Копировать/Удалить» → «Сохранить/Отмена». */
function enterEditMode(card) {
    const textBlock = card.querySelector(".post-card-text");
    if (!textBlock || card.classList.contains("editing")) return;

    const post = postsCache.find((item) => item.id === card.dataset.id);
    if (!post) return;

    card.classList.add("editing");

    const textarea = document.createElement("textarea");
    textarea.className = "post-card-edit";
    textarea.value = post.text || "";
    textarea.setAttribute("aria-label", "Текст поста");
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight + 4, 320) + "px";
    textarea.addEventListener("input", () => {
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight + 4, 320) + "px";
    });
    card.replaceChild(textarea, textBlock);

    const buttons = card.querySelectorAll(".post-card-actions button");
    buttons.forEach((btn) => {
        if (btn.classList.contains("js-edit") ||
            btn.classList.contains("js-copy") ||
            btn.classList.contains("js-delete")) {
            btn.hidden = true;
        } else {
            btn.hidden = false;
        }
    });

    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
}

/* ------------------------------------------------------------------
   СТАРТ: подтягиваем сохранённые посты при загрузке страницы
------------------------------------------------------------------ */
loadPosts();

/* ------------------------------------------------------------------
   СКРЫВАЕМ ОШИБКИ, КАК ТОЛЬКО ПОЛЬЗОВАТЕЛЬ НАЧИНАЕТ ПЕЧАТАТЬ.
------------------------------------------------------------------ */
descriptionInput.addEventListener("input", () => {
    toggleError(descriptionInput, descriptionError, false);
});

linkInput.addEventListener("input", () => {
    toggleError(linkInput, linkError, false);
});

/* ------------------------------------------------------------------
   КОПИРОВАНИЕ ПОСТА В БУФЕР ОБМЕНА.
   Используем современный Clipboard API, а для старых браузеров —
   запасной способ через выделение текста (execCommand).
------------------------------------------------------------------ */
copyButton.addEventListener("click", async () => {
    const text = postOutput.textContent;

    try {
        // Современный способ (работает в Chrome, Edge, Firefox, Safari).
        await navigator.clipboard.writeText(text);
    } catch {
        // Запасной способ: выделяем текст внутри блока и копируем.
        const range = document.createRange();
        range.selectNodeContents(postOutput);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand("copy");
        selection.removeAllRanges();
    }

    // Показываем сообщение «Пост скопирован» на пару секунд.
    copyFeedback.hidden = false;
    setTimeout(() => { copyFeedback.hidden = true; }, 2000);
});

/* =========================================================================
   ПАКЕТНАЯ ГЕНЕРАЦИЯ
   ========================================================================= */
const batchInput     = document.getElementById("batch-input");
const batchError     = document.getElementById("batch-input-error");
const batchFile      = document.getElementById("batch-file");
const batchCheckBtn  = document.getElementById("batch-check-btn");
const batchSummary   = document.getElementById("batch-summary");
const batchColsHint  = document.getElementById("batch-cols-hint");
const batchMood      = document.getElementById("batch-mood");
const batchExample   = document.getElementById("batch-example");
const batchModeBtns  = document.querySelectorAll(".mode-btn[data-batch-mode]");

/* Подрежим пакетной генерации: "template" или "ai" */
let batchMode = "template";

/* Результат последней проверки — нужен после модалки с дубликатами */
let lastBatchCheck = null;

const BATCH_TEXTS = {
    template: {
        hint: "Колонки через таб, «;» или «,»: название | описание* | выгода | настроение",
        placeholder: "Вставь строки из Excel или CSV — по одной строке на товар",
        example:
            "Название\tОписание\tВыгода\tНастроение\n" +
            "Керамическая кружка\tДержит температуру 60 минут\t1 990 ₽\tяркий\n" +
            "Набор кистей\t12 кистей из натурального ворса\tСкидка 20%\tдружелюбный",
    },
    ai: {
        hint: "Колонки через таб, «;» или «,»: ссылка | настроение",
        placeholder: "Вставь ссылки на страницы товаров — по одной на строку",
        example:
            "Ссылка\tНастроение\n" +
            "https://example.ru/product/1\tяркий\n" +
            "https://example.ru/product/2\tделовой",
    },
};

/* Переключение «Шаблон / Нейросеть» внутри пакетного режима */
function setBatchMode(mode) {
    batchMode = mode;
    batchModeBtns.forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.batchMode === mode);
    });

    const texts = BATCH_TEXTS[mode];
    batchColsHint.textContent = texts.hint;
    batchInput.placeholder = texts.placeholder;
    batchExample.textContent = texts.example;
}

batchModeBtns.forEach((btn) => {
    btn.addEventListener("click", () => setBatchMode(btn.dataset.batchMode));
});

/* Загрузка файла: читаем текст и кладём в поле вставки */
batchFile.addEventListener("change", async () => {
    const file = batchFile.files && batchFile.files[0];
    if (!file) return;

    if (file.size > 1_000_000) {
        showToast("Файл больше 1 МБ — уменьши список", true);
        batchFile.value = "";
        return;
    }

    try {
        batchInput.value = await file.text();
        toggleError(batchInput, batchError, false);
        showToast(`Файл «${file.name}» загружен — нажми «Проверить список»`);
    } catch {
        showToast("Не удалось прочитать файл", true);
    }
    batchFile.value = "";
});

/* Показать/скрыть ошибку под полем списка */
batchInput.addEventListener("input", () => {
    toggleError(batchInput, batchError, false);
});

/* ------------------------------------------------------------------
   ПРОВЕРКА СПИСКА: парсинг + генерация + поиск дубликатов
------------------------------------------------------------------ */
batchCheckBtn.addEventListener("click", async () => {
    const content = batchInput.value.trim();
    if (!content) {
        batchError.textContent = "Вставь список — пока нечего проверять";
        toggleError(batchInput, batchError, true);
        batchInput.focus();
        return;
    }

    batchCheckBtn.disabled = true;
    const busyText = batchMode === "ai" ? "Нейросеть работает…" : "Проверяю…";
    batchCheckBtn.textContent = busyText;
    batchSummary.hidden = true;

    try {
        const data = await api("/api/batch/check", "POST", {
            content,
            mode: batchMode,
            mood_default: batchMood.value,
        });

        lastBatchCheck = data;

        // Чистим содержимое модалки от прошлого раза — иначе старые чекбоксы
        // могли бы попасть в подсчёт, даже если модалка не открывалась.
        modalExtra.innerHTML = "";
        modalExtra.hidden = true;

        if (data.duplicates && data.duplicates.length) {
            // Дубликаты есть — спрашиваем пользователя, грузить ли их.
            const proceed = await askDuplicates(data.duplicates);
            if (!proceed) {
                renderBatchSummary(data, { created: 0, skipped: 0, cancel: true });
                return;
            }
            await createBatchPosts(data);
        } else {
            await createBatchPosts(data);
        }
    } catch (error) {
        batchError.textContent = error.message;
        toggleError(batchInput, batchError, true);
        batchSummary.hidden = true;
    } finally {
        batchCheckBtn.disabled = false;
        batchCheckBtn.textContent = "Проверить список";
    }
});

/* ------------------------------------------------------------------
   МОДАЛКА ДУБЛИКАТОВ: пользователь отмечает, что всё-таки грузить.
   Чекбоксы по умолчанию ВЫКЛЮЧЕНЫ — без галочки дубликат не загрузится.
------------------------------------------------------------------ */
function askDuplicates(duplicates) {
    return openModal({
        title: "Найдены дубликаты",
        text: `Похожие посты уже есть${duplicates.length > 1 ? " (" + duplicates.length + " шт.)" : ""}. ` +
              "Отметь галочками те, которые всё-таки нужно загрузить. " +
              "Без отметки дубликат будет пропущен.",
        confirmLabel: "Загрузить список",
        cancelLabel: "Отмена",
        danger: false,
        buildExtra(container) {
            duplicates.forEach((dup) => {
                const row = document.createElement("label");
                row.className = "dup-row";

                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.dataset.index = String(dup.index);

                const main = document.createElement("span");
                main.className = "dup-row-main";

                const name = document.createElement("span");
                name.className = "dup-row-name";
                name.textContent = `Строка ${dup.index}. ${dup.name || "Без названия"}`;

                const info = document.createElement("span");
                info.className = "dup-row-info";
                info.textContent = dup.in_batch
                    ? `Полный дубликат — ${dup.target_name}`
                    : `Совпадает на ${dup.similarity}% с постом «${dup.target_name}»` +
                      (dup.target_date ? ` от ${formatDate(dup.target_date)}` : "");

                main.append(name, info);
                row.append(checkbox, main);
                container.appendChild(row);
            });

            const total = document.createElement("p");
            total.className = "dup-total";
            container.appendChild(total);

            const recount = () => {
                const checkedCount = container.querySelectorAll(
                    'input[type="checkbox"]:checked',
                ).length;
                total.textContent = checkedCount
                    ? `Будет загружено с дубликатами: ${checkedCount} из ${duplicates.length}`
                    : "Дубликаты загружаться не будут";
            };

            container.addEventListener("change", recount);
            recount();
        },
    });
}

/* ------------------------------------------------------------------
   ЗАГРУЗКА ПРОВЕРЕННЫХ СТРОК
------------------------------------------------------------------ */
async function createBatchPosts(data) {
    // Строки без ошибок, из которых исключаем неподтверждённые дубликаты.
    const checkedDupes = new Set(
        [...modalExtra.querySelectorAll('input[type="checkbox"]:checked')]
            .map((box) => Number(box.dataset.index)),
    );

    const candidates = data.rows.filter(
        (row) => !row.error && row.text &&
                 (!row.duplicate || checkedDupes.has(row.index)),
    );
    const skipped = data.duplicates
        ? data.duplicates.filter((dup) => !checkedDupes.has(dup.index)).length
        : 0;

    if (!candidates.length) {
        renderBatchSummary(data, { created: 0, skipped, cancel: false });
        showToast("Нечего загружать — все строки отсеяны", true);
        return;
    }

    const items = candidates.map((row) => ({
        index: row.index,
        name: row.name,
        text: row.text,
        mood: row.mood,
        mode: batchMode,
    }));

    try {
        const result = await api("/api/batch/create", "POST", { items });
        renderBatchSummary(data, {
            created: result.created,
            skipped,
            cancel: false,
            createErrors: result.errors || [],
        });
        showToast(`Загружено постов: ${result.created}`);
        await loadPosts();
        batchSummary.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
        showToast("Не удалось загрузить: " + error.message, true);
    }
}

/* ------------------------------------------------------------------
   ИТОГ: строки со статусами «создано / пропущено / ошибка»
------------------------------------------------------------------ */
function renderBatchSummary(data, outcome) {
    const createErrorIndexes = new Set(
        (outcome.createErrors || []).map((err) => err.index),
    );
    const skippedIndexes = new Set(
        data.duplicates
            ? data.duplicates.map((dup) => dup.index)
            : [],
    );

    // Отмеченные в модалке дубликаты — они НЕ пропущены.
    [...modalExtra.querySelectorAll('input[type="checkbox"]:checked')]
        .forEach((box) => skippedIndexes.delete(Number(box.dataset.index)));

    const errorCount = data.errors + (outcome.createErrors || []).length;
    const validCount = data.valid;

    const header = document.createElement("h4");
    if (outcome.cancel) {
        header.textContent = "Загрузка отменена — ни один пост не сохранён";
    } else {
        header.textContent =
            `Строк: ${data.total} · Загружено: ${outcome.created} · ` +
            `Пропущено дубликатов: ${outcome.skipped} · Ошибок: ${errorCount}`;
    }
    batchSummary.innerHTML = "";
    batchSummary.appendChild(header);

    data.rows.forEach((row) => {
        const line = document.createElement("div");
        line.className = "batch-row";

        const num = document.createElement("span");
        num.className = "batch-row-num";
        num.textContent = row.index;

        const name = document.createElement("span");
        name.className = "batch-row-name";
        name.textContent = row.name || row.error || "Без названия";

        const status = document.createElement("span");
        status.className = "batch-row-status";

        let reason = null;
        if (row.error) {
            status.textContent = "Ошибка";
            status.classList.add("status-error");
            reason = document.createElement("span");
            reason.className = "batch-row-reason";
            reason.textContent = row.error;
        } else if (createErrorIndexes.has(row.index)) {
            status.textContent = "Ошибка";
            status.classList.add("status-error");
            reason = document.createElement("span");
            reason.className = "batch-row-reason";
            const err = (outcome.createErrors || [])
                .find((item) => item.index === row.index);
            reason.textContent = err ? err.error : "не удалось сохранить";
        } else if (outcome.cancel) {
            status.textContent = "Отменено";
            status.classList.add("status-skip");
        } else if (skippedIndexes.has(row.index)) {
            status.textContent = "Дубликат — пропущен";
            status.classList.add("status-skip");
        } else {
            status.textContent = "Создано";
            status.classList.add("status-ok");
        }

        line.append(num, name, status);
        if (reason) line.appendChild(reason);
        batchSummary.appendChild(line);
    });

    batchSummary.hidden = false;
}