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
const modeButtons       = document.querySelectorAll(".mode-btn");
const templateGroup     = document.getElementById("template-group");
const aiGroup           = document.getElementById("ai-group");

/* Текущий режим: "template" или "ai" */
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

    // Сбрасываем ошибки при смене режима.
    toggleError(descriptionInput, descriptionError, false);
    toggleError(linkInput, linkError, false);
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