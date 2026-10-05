"""
==============================
 Генератор постов для товара
==============================

Учебный проект на Flask без базы данных.
Есть два режима генерации поста:

  1. Шаблон  — текст собирается из готовых шаблонов (без интернета).
  2. Нейросеть — пользователь даёт ссылку на страницу товара,
                 сервер достаёт текст и отдаёт его AI (OpenAI-совместимый API),
                 чтобы написать пост.

Как запустить:
    python app.py
    затем открой в браузере: http://127.0.0.1:5000

Структура проекта:
    app.py              — это приложение (весь сервер)
    templates/index.html — страница (HTML + шаблон Jinja)
    static/style.css    — стили страницы
    static/script.js    — логика на стороне браузера
    voice.md            — описание настроек голоса (настроений)
    .env                — настройки нейросети (ключ API, модель, адрес)

Нейросеть работает только с ключом API:
    скопируй файл .env.example в .env и впиши OPENAI_API_KEY.
    Поддерживаются любые OpenAI-совместимые сервисы:
    OpenAI, DeepSeek, OpenRouter, локальные модели через Ollama и др.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# НАСТРОЙКИ ГОЛОСА (VOICE)
# ---------------------------------------------------------------------------
# Здесь описаны возможные «настроения» поста: тон, длина, эмодзи, стиль заголовка.
# Эти же настройки подробно описаны в файле voice.md.
# Чтобы добавить новое настроение — просто добавь блок в словарь VOICES.
# ---------------------------------------------------------------------------

# Шаблоны текста для режима «Шаблон».
TEMPLATE = {
    "яркий": (
        "✨ Такого вы ещё не видели!\n\n"
        "{name} — это именно то, что сделает твой день ярче. {description}\n\n"
        "🔥 {benefit}\n\n"
        "Забирай сейчас — пока есть в наличии! 💛"
    ),
    "деловой": (
        "{name}: надёжное решение для ваших задач.\n\n"
        "{description}\n\n"
        "Ключевое преимущество: {benefit}.\n\n"
        "Оформите заказ прямо сейчас — мы на связи с вами на каждом этапе."
    ),
    "дружелюбный": (
        "Привет-привет! 👋 Хочу рассказать тебе про {name}.\n\n"
        "{description}\n\n"
        "А бонус такой — {benefit} 🥰\n\n"
        "Спрашивай в сообщениях — расскажу все детали!"
    ),
}

# Эмодзи в конце поста в зависимости от настроения (режим «Шаблон»).
# Если поставить пустую строку "" — эмодзи не будет.
EMOJI_AFTER = {
    "яркий": "🎉",
    "деловой": "📌",
    "дружелюбный": "💛",
}

# ---------------------------------------------------------------------------
# НАСТРОЙКИ «ГОЛОСА» ДЛЯ НЕЙРОСЕТИ
# ---------------------------------------------------------------------------
# Эти настройки передаются нейросети в виде правил в системном сообщении.
# Меняй их тут — и «голос» постов изменится сразу во всех AI-генерациях.
# Полное описание — в файле voice.md.
# ---------------------------------------------------------------------------

# Как нейросеть должна звучать для каждого настроения.
AI_MOOD_TONES = {
    "яркий": "воодушевлённый, энергичный, с восклицаниями",
    "деловой": "деловой, уверенный, спокойный; обращение на «вы»",
    "дружелюбный": "тёплый и разговорный, обращение на «ты»",
}

# Длина поста: короткий / средний / длинный.
AI_POST_LENGTH = "средний"

# Сколько эмодзи добавлять: "пару штук" / "минимально" / "много". 
AI_EMOJI_COUNT = "пару штук, уместных по теме"

# Стиль заголовка: строгий / креативный.
AI_TITLE_STYLE = "как диктует настроение: яркий — креативный, деловой — строгий, дружелюбный — разговорный"

# Максимум символов текста страницы, который уходит нейросети.
# Больше не нужно — дорого и медленно.
MAX_PAGE_CHARS = 10000


# ---------------------------------------------------------------------------
# НАСТРОЙКИ НЕЙРОСЕТИ (ПОДКЛЮЧЕНИЕ К API)
# ---------------------------------------------------------------------------
def load_dotenv():
    """
    Мини-загрузчик файла .env (без сторонних библиотек).
    .env лежит рядом с app.py и содержит переменные окружения.
    Значения уже существующих переменных окружения не перезаписываем.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return  # файла нет — просто работаем со значениями по умолчанию

    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Пропускаем пустые строки и комментарии (# ...).
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()  # подключаем .env при старте приложения

# Ключ API нейросети (впиши в .env).
AI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Базовый адрес API. По умолчанию — OpenAI.
# Для DeepSeek:      https://api.deepseek.com/v1
# Для OpenRouter:    https://openrouter.ai/api/v1
# Для Ollama локально: http://localhost:11434/v1
AI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

# Название модели.
# Для OpenAI:       gpt-4o-mini / gpt-4o
# Для DeepSeek:     deepseek-chat
# Для Ollama:       совпадает с именем скачанной модели (llama3 и т.п.)
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")


class AIGenerationError(Exception):
    """Пользовательская ошибка генерации — её текст покажем на странице."""


# ---------------------------------------------------------------------------
# РЕЖИМ «ШАБЛОН»: сборка поста без нейросети
# ---------------------------------------------------------------------------
def build_post(name, description, benefit, mood):
    """
    Собирает текст поста по шаблону для выбранного настроения.
    Все аргументы приходят из формы (см. index()).
    """
    # Безопасно достаём шаблон; если настроения нет — используем «деловой».
    template = TEMPLATE.get(mood, TEMPLATE["деловой"])

    # Подставляем данные пользователя в шаблон.
    post = template.format(
        name=name or "Товар",          # если название пустое — подставляем заглушку
        description=description,
        benefit=benefit or "выгодная цена",
    )

    # Добавляем заключительное настроение-эмодзи, если оно настроено.
    final_emoji = EMOJI_AFTER.get(mood)
    if final_emoji:
        post += f"\n\n{final_emoji}"

    return post


# ---------------------------------------------------------------------------
# РЕЖИМ «НЕЙРОСЕТЬ»: чтение страницы по ссылке и вызов AI
# ---------------------------------------------------------------------------
def fetch_page_text(link):
    """
    Открывает ссылку и возвращает текст страницы без HTML-разметки.
    Если страница не открылась или текста нет — бросаем AIGenerationError.
    """
    # Проверяем схему ссылки — разрешаем только обычные сайты.
    scheme = urllib.parse.urlparse(link).scheme.lower()
    if scheme not in ("http", "https"):
        raise AIGenerationError("Ссылка должна начинаться с http:// или https://")

    # Притворяемся обычным браузером, чтобы сайты нас не блокировали,
    # и просим отдавать данные без сжатия (урлы сразу не умеет распаковывать).
    request = urllib.request.Request(
        link,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept-Encoding": "identity",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read()
            # Берём кодировку из заголовков сайта, если она есть.
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        raise AIGenerationError(f"Страница не открылась (ошибка {e.code}). Проверь ссылку.")
    except urllib.error.URLError:
        raise AIGenerationError("Не удалось открыть страницу. Проверь ссылку и интернет.")

    # Декодируем байты в текст. Если сайт указал неизвестную кодировку — откатываемся на UTF-8.
    try:
        text = content.decode(charset, errors="replace")
    except LookupError:
        text = content.decode("utf-8", errors="replace")

    # Убираем скрипты, стили и всю HTML-разметку, схлопываем пробелы.
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Ограничиваем размер текста — иначе запрос к нейросети будет дорогим.
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + " …"

    # Если на странице почти нет текста, это бесполезно для нейросети.
    if len(text) < 100:
        raise AIGenerationError("На странице не нашлось текста о товаре.")

    return text


def call_neuro(messages):
    """
    Отправляет диалог в OpenAI-совместимый API и возвращает ответ модели
    как строку. Всё через стандартный модуль urllib — библиотек не нужно.
    """
    url = f"{AI_BASE_URL}/chat/completions"

    payload = json.dumps({
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.8,  # чуть-чуть творчества, но без полёта фантазии
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Читаем тело ошибки, там может быть объяснение (например, про ключ).
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise AIGenerationError("Нейросеть не пускает: неверный ключ API. Проверь OPENAI_API_KEY в .env.")
        if e.code == 429:
            raise AIGenerationError("Слишком много запросов к нейросети (лимит). Попробуй позже.")
        raise AIGenerationError(f"Нейросеть вернула ошибку {e.code}: {body[:200]}")
    except urllib.error.URLError:
        raise AIGenerationError("Не удалось связаться с нейросетью. Проверь интернет и OPENAI_BASE_URL в .env.")

    # У OpenAI-совместимых сервисов ответ лежит в data["choices"][0]["message"]["content"].
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise AIGenerationError("Нейросеть ответила неожиданным образом: " + json.dumps(data, ensure_ascii=False)[:200])


def build_ai_messages(mood, page_text):
    """
    Собирает диалог для нейросети: системные правила «голоса» + текст страницы.
    Настроение (тон) выбирает пользователь в форме.
    """
    # Тон из словаря; если настроения нет вообще — запасной вариант «деловой».
    tone = AI_MOOD_TONES.get(mood, AI_MOOD_TONES["деловой"])

    system = (
        "Ты — опытный копирайтер для соцсетей. Напиши готовый пост о товаре "
        "на основе текста страницы, которую даст пользователь.\n\n"
        "Правила:\n"
        f"- Стиль заголовка: {AI_TITLE_STYLE}.\n"
        f"- Общий тон: {tone}.\n"
        f"- Длина поста: {AI_POST_LENGTH}.\n"
        f"- Эмодзи: {AI_EMOJI_COUNT}.\n"
        "- В конце — короткий призыв к действию.\n"
        "- Не выдумывай факты, которых нет на странице.\n"
        "- Название товара, цену и выгоды возьми из текста страницы.\n"
        "- Отвечай только самим текстом поста, без предисловий и пояснений."
    )

    user = f"Текст страницы о товаре:\n{page_text}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# ГЛАВНАЯ СТРАНИЦА
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Отдаёт HTML-страницу."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# РЕЖИМ «ШАБЛОН» — POST-запрос из формы (AJAX)
# ---------------------------------------------------------------------------
@app.route("/generate", methods=["POST"])
def generate():
    """
    Принимает данные из JavaScript:
      - name        (название товара)
      - description (описание товара, ОБЯЗАТЕЛЬНОЕ)
      - benefit     (цена или выгода)
      - mood        (настроение поста)

    Если description пустой — возвращаем JSON с ошибкой (код 400),
    чтобы страница показала предупреждение.
    """
    data = request.get_json(silent=True) or {}

    # Обязательное поле — описание товара.
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "Опишите товар — без этого пост не собрать"}), 400

    # Необязательные поля — с запасными значениями.
    name = (data.get("name") or "").strip()
    benefit = (data.get("benefit") or "").strip()
    mood = (data.get("mood") or "").strip() or "яркий"

    # Собираем текст поста.
    post = build_post(name, description, benefit, mood)

    return jsonify({"post": post})


# ---------------------------------------------------------------------------
# РЕЖИМ «НЕЙРОСЕТЬ» — POST-запрос из формы (AJAX)
# ---------------------------------------------------------------------------
@app.route("/generate-ai", methods=["POST"])
def generate_ai():
    """
    Принимает данные из JavaScript:
      - link (ссылка на страницу товара, ОБЯЗАТЕЛЬНАЯ)
      - mood (настроение поста — тон задаёт пользователь)

    Название и цену нейросеть определяет сама по тексту страницы.
    """
    data = request.get_json(silent=True) or {}

    # Обязательное поле — ссылка на товар.
    link = (data.get("link") or "").strip()
    if not link:
        return jsonify({"error": "Вставь ссылку на товар — без неё нейросеть не соберёт пост"}), 400

    # Настроение выбирает пользователь (по умолчанию — «яркий»).
    mood = (data.get("mood") or "").strip() or "яркий"

    # Если ключ не вписан в .env — сразу понятная ошибка, не ждём таймаута.
    if not AI_API_KEY:
        return jsonify({
            "error": "Нет ключа API. Скопируй .env.example в .env и впиши OPENAI_API_KEY, затем перезапусти сервер."
        }), 500

    try:
        # 1. Открываем страницу по ссылке и забираем её текст.
        page_text = fetch_page_text(link)

        # 2. Собираем диалог для нейросети и получаем пост.
        post = call_neuro(build_ai_messages(mood, page_text))
    except AIGenerationError as e:
        # Любая понятная ошибка превращается в JSON с кодом 400 —
        # страница покажет её под полем ссылки.
        return jsonify({"error": str(e)}), 400

    return jsonify({"post": post})


# ---------------------------------------------------------------------------
# ЗАПУСК
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # debug=True перезапускает сервер при изменении кода —
    # удобно для экспериментов.
    app.run(debug=True)