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

import csv
import difflib
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

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
# {name_nom} / {name_acc} и т.д. — название товара в нужном падеже
# (падеж подставляет функция decline_phrase, см. ниже).
TEMPLATE = {
    "яркий": (
        "✨ Такого вы ещё не видели!\n\n"
        "{name_nom} — это именно то, что сделает твой день ярче. {description}\n\n"
        "🔥 {benefit}\n\n"
        "Забирай сейчас — пока есть в наличии! 💛"
    ),
    "деловой": (
        "{name_nom}: надёжное решение для ваших задач.\n\n"
        "{description}\n\n"
        "Ключевое преимущество: {benefit}.\n\n"
        "Оформите заказ прямо сейчас — мы на связи с вами на каждом этапе."
    ),
    "дружелюбный": (
        "Привет-привет! 👋 Хочу рассказать тебе про {name_acc}.\n\n"
        "{description}\n\n"
        "А бонус такой — {benefit} 🥰\n\n"
        "Спрашивай в сообщениях — расскажу все детали!"
    ),
}

# Падеж по умолчанию для каждого настроения — используется,
# когда пользователь не выбрал падеж вручную (селект «Авто»).
TEMPLATE_MOOD_CASE = {
    "яркий": "nom",
    "деловой": "nom",
    "дружелюбный": "acc",
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
# СКЛОНЕНИЕ НАЗВАНИЯ ТОВАРА ПО ПАДЕЖАМ
# ---------------------------------------------------------------------------
# Свои правила на русский язык, без библиотек (pymorphy не ставим).
# Работает по окончаниям слов: существительные (род по окончанию),
# прилагательные, местоимения не обрабатываются. Латиница, цифры,
# аббревиатуры и слова из списка INVARIANT не склоняются.
#
# Ограничения (честно):
#   - мужской род в винительном считается неодушевлённым (= именительный):
#     «кружка» / «товар» — ок, но «купить кот» станет «купить кот»;
#   - слова на «-ь» без словаря считаются мужскими (исключения — FEMENINE_SOFT);
#   - ударения не учитываются, поэтому редкие разговорные формы могут быть неточны.
#   Ручной выбор падежа в форме — запасной вариант на случай ошибки автоматики.
# ---------------------------------------------------------------------------

CASES = ("nom", "gen", "dat", "acc", "ins", "prep")

CASES_RU = {
    "nom": "Именительный (кто? что?)",
    "gen": "Родительный (кого? чего?)",
    "dat": "Дательный (кому? чему?)",
    "acc": "Винительный (кого? что?)",
    "ins": "Творительный (кем? чем?)",
    "prep": "Предложный (о ком? о чём?)",
}

# Неизменяемые слова (заимствования и исключения).
INVARIANT = {
    "кофе", "пальто", "шоссе", "плато", "желе", "шасси",
    "метро", "пюре", "кино", "трико", "пенье",
}

# Женские слова на «-ь» (по умолчанию «-ь» = мужской род).
FEMENINE_SOFT = {
    "ночь", "речь", "вещь", "помощь", "дверь", "цель", "соль",
    "моль", "тень", "любовь", "радость", "новость", "горсть",
    "честь", "мочь", "власть", "часть", "кость", "плеть", "петля",
}

# Служебные слова: их самих не склоняем.
PREPOSITIONS = {
    "в", "во", "с", "со", "на", "по", "для", "к", "ко", "у", "о", "об",
    "обо", "от", "из", "до", "без", "под", "над", "при", "про", "за",
    "через", "между", "ради", "для", "или",
}
CONJUNCTIONS = {"и", "а", "но", "не", "ни", "да", "что", "как", "или", "либо"}

VELAR = "гкх"          # велярные: после них буква «ы» не пишется
HISSER = "жчшщ"        # шипящие

# Целое слово: только кириллица, возможно через дефис, без цифр и латиницы.
WORD_RE = re.compile(r"^[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*$")


def _decline_adjective(word, case):
    """Склоняет прилагательное по окончанию (ый/ий/ой, ая/яя, ое/ее, ые/ие)."""
    # Мужской род: хороший/русский/доброй
    if word.endswith(("ый", "ий", "ой")):
        stem = word[:-2]
        last = stem[-1] if stem else ""
        # твёрдое окончание: -ый/-ой, велярные, ц; шипящие дают -его/-ему
        hard = word.endswith(("ый", "ой")) or last in VELAR or last == "ц"
        return stem + {
            "gen": "ого" if hard else "его",
            "dat": "ому" if hard else "ему",
            "acc": word,                       # неодушевлённое = именительный
            "ins": "ым" if hard else "им",
            "prep": "ом" if hard else "ем",
        }.get(case, word)

    # Женский род: русская/синяя
    if word.endswith(("ая", "яя")):
        stem = word[:-2]
        soft = word.endswith("яя")
        return stem + {
            "gen": "ей" if soft else "ой",
            "dat": "ей" if soft else "ой",
            "acc": "юю" if soft else "ую",
            "ins": "ей" if soft else "ой",
            "prep": "ей" if soft else "ой",
        }.get(case, word)

    # Средний род: хорошее/синее
    if word.endswith(("ое", "ее")):
        stem = word[:-2]
        last = stem[-1] if stem else ""
        hard = word.endswith("ое") or last in VELAR or last == "ц"
        return stem + {
            "gen": "ого" if hard else "его",
            "dat": "ому" if hard else "ему",
            "acc": word,
            "ins": "ым" if hard else "им",
            "prep": "ом" if hard else "ем",
        }.get(case, word)

    # Множественное число: хорошие/русские
    if word.endswith(("ые", "ие")):
        stem = word[:-2]
        soft = word.endswith("ие")
        plural = {
            "gen": "их" if soft else "ых",
            "dat": "им" if soft else "ым",
            "acc": word,
            "ins": "ими" if soft else "ыми",
            "prep": "их" if soft else "ых",
        }
        return stem + plural.get(case, word)

    return word


def _decline_noun(word, case):
    """Склоняет существительное по окончанию (род определяется по окончанию)."""
    # --- Средний род: окно, море ---
    if word.endswith("о"):
        stem = word[:-1]
        return stem + {
            "gen": "а", "dat": "у", "acc": word, "ins": "ом", "prep": "е",
        }.get(case, word)
    if word.endswith(("е", "ё")):
        stem = word[:-1]
        return stem + {
            "gen": "я", "dat": "ю", "acc": word, "ins": "ем", "prep": "е",
        }.get(case, word)

    # --- Женский род: кружка, неделя, станция ---
    if word.endswith("а"):
        stem = word[:-1]
        last = stem[-1] if stem else ""
        if case == "gen":
            # «книга» → «книги», но «папка» → «папки»
            return stem + ("и" if last in VELAR + HISSER + "цй" else "ы")
        return stem + {
            "dat": "е", "acc": "у", "ins": "ой", "prep": "е",
        }.get(case, word)

    if word.endswith("ия"):
        stem = word[:-1]
        return stem + {
            "gen": "и", "dat": "и", "acc": "ю", "ins": "ей", "prep": "и",
        }.get(case, word)
    if word.endswith("я"):
        stem = word[:-1]
        return stem + {
            "gen": "и", "dat": "е", "acc": "ю", "ins": "ей", "prep": "е",
        }.get(case, word)

    # --- Мужской род на -й: чай, гений ---
    if word.endswith("й"):
        stem = word[:-1]
        return stem + {
            "gen": "я", "dat": "ю", "acc": word, "ins": "ем", "prep": "е",
        }.get(case, word)

    # --- Мужской род на -ь: гель, ночь(исключение — женский) ---
    if word.endswith("ь"):
        if word in FEMENINE_SOFT:
            stem = word[:-1]
            return stem + {
                "gen": "и", "dat": "и", "acc": "ь", "ins": "ью", "prep": "и",
            }.get(case, word)
        stem = word[:-1]
        return stem + {
            "gen": "я", "dat": "ю", "acc": word, "ins": "ем", "prep": "е",
        }.get(case, word)

    # --- Мужской род на согласный: товар, ноутбук ---
    if word and word[-1] not in "аеёуыэйьюия":
        last = word[-1]
        if case == "acc":
            return word                        # неодушевлённое = именительный
        return word + {
            "gen": "а", "dat": "у",
            "ins": "ем" if last == "ц" else "ом",
            "prep": "е",
        }.get(case, word)

    return word


def decline_word(word, case):
    """Склоняет одно слово в падеж case. Число/латиница/исключения — как есть."""
    if case not in CASES or case == "nom":
        return word
    if not WORD_RE.match(word):
        return word                                # цифры, латиница, «iPhone 15»
    if "-" in word:                                # составные слова по частям
        return "-".join(decline_word(part, case) for part in word.split("-"))
    if word.lower() in INVARIANT:
        return word

    lowered = word.lower()

    # Сначала пробуем как прилагательное, потом как существительное.
    if lowered.endswith(("ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые", "ие")):
        declined = _decline_adjective(lowered, case)
    else:
        declined = _decline_noun(lowered, case)

    # Сохраняем регистр первой буквы («Керамическая» → «Керамической»).
    if word[0].isupper():
        declined = declined.capitalize()
    return declined


def decline_phrase(phrase, case):
    """
    Склоняет название целиком — по словам.
    Служебные слова (предлоги, союзы) не трогаем, а слово после предлога
    оставляем в покое: «Кружка с подогревом» → «Кружке с подогревом».
    """
    if case not in CASES or case == "nom" or not phrase:
        return phrase

    tokens = re.split(r"([^А-Яа-яЁё\-]+)", phrase)
    result = []
    skip_next = False

    for token in tokens:
        if not token or not WORD_RE.match(token):
            result.append(token)                   # пробелы, цифры, знаки
            continue

        lowered = token.lower()
        if lowered in PREPOSITIONS:
            result.append(token)
            skip_next = True                        # слово после предлога не трогаем
            continue
        if lowered in CONJUNCTIONS:
            result.append(token)
            continue
        if skip_next:
            result.append(token)
            skip_next = False
            continue

        result.append(decline_word(token, case))
        skip_next = False

    return "".join(result)


# ---------------------------------------------------------------------------
# РЕЖИМ «ШАБЛОН»: сборка поста без нейросети
# ---------------------------------------------------------------------------
def build_post(name, description, benefit, mood, name_case=""):
    """
    Собирает текст поста по шаблону для выбранного настроения.
    name_case — падеж из формы ("" = авто, падеж шаблона).
    """
    # Безопасно достаём шаблон; если настроения нет — используем «деловой».
    template = TEMPLATE.get(mood, TEMPLATE["деловой"])

    # Название по умолчанию — заглушка.
    name = name or "Товар"

    # Склоняем название во все падежи — шаблон сам выберет слот
    # ({name_nom}, {name_acc}, …). При ручном выборе падежа все слоты
    # получают одну и ту же форму.
    if name_case:
        fields = {f"name_{case}": decline_phrase(name, name_case) for case in CASES}
    else:
        fields = {f"name_{case}": decline_phrase(name, case) for case in CASES}

    # Ключ {name} (если появится в новом шаблоне) — падеж шаблона или ручной.
    default_case = name_case or TEMPLATE_MOOD_CASE.get(mood, "nom")
    fields["name"] = decline_phrase(name, default_case)

    # Подставляем данные пользователя в шаблон.
    post = template.format(
        description=description,
        benefit=benefit or "выгодная цена",
        **fields,
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
        "- Ставь название товара в том падеже, который нужен по контексту "
        "предложения: не «рассказать про Керамическая кружка», "
        "а «рассказать про Керамическую кружку».\n"
        "- Отвечай только самим текстом поста, без предисловий и пояснений."
    )

    user = f"Текст страницы о товаре:\n{page_text}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# ХРАНИЛИЩЕ ПОСТОВ (posts.json)
# ---------------------------------------------------------------------------
# Посты лежат в файле data/posts.json рядом с app.py.
# Формат: список объектов {id, name, text, mood, mode, hashtags, created_at, updated_at}.
# Запись атомарная (пишем во временный файл и подменяем) — чтобы при сбое
# старый файл остался целым.
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
POSTS_FILE = os.path.join(DATA_DIR, "posts.json")

# Ограничения полей — чтобы хранилище не разрасталось и UI не ломался.
MAX_POST_TEXT = 5000
MAX_POST_NAME = 200
MAX_HASHTAGS = 30
MAX_HASHTAG_LEN = 50

# Допустимые настроения (совпадает с ключами шаблонов).
MOODS = set(TEMPLATE.keys())


def now_iso():
    """Текущее время в ISO-формате (UTC) — для created_at / updated_at."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_posts():
    """Читает список постов из файла. Повреждённый файл = пустой список."""
    if not os.path.exists(POSTS_FILE):
        return []
    try:
        with open(POSTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_posts(posts):
    """Сохраняет список постов в файл (атомарно)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = POSTS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, POSTS_FILE)


def validate_post_payload(data, partial=False):
    """
    Проверяет поля поста. Возвращает (clean, errors):
      clean  — словарь с очищенными полями (только переданные),
      errors — список сообщений об ошибках.
    partial=True — проверяем только присланные поля (для PUT).
    """
    clean, errors = {}, []

    if not partial or "name" in data:
        name = str(data.get("name") or "").strip()
        if len(name) > MAX_POST_NAME:
            errors.append(f"Название длиннее {MAX_POST_NAME} знаков")
        clean["name"] = name

    if not partial or "text" in data:
        text = str(data.get("text") or "").strip()
        if not text:
            errors.append("Текст поста пустой")
        elif len(text) > MAX_POST_TEXT:
            errors.append(f"Текст поста длиннее {MAX_POST_TEXT} знаков")
        clean["text"] = text

    if "mood" in data:
        mood = str(data.get("mood") or "").strip()
        if mood and mood not in MOODS:
            errors.append("Неизвестное настроение поста")
        clean["mood"] = mood

    if "hashtags" in data:
        raw = data.get("hashtags")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            errors.append("Хештеги должны быть списком")
        else:
            tags = []
            for tag in raw[:MAX_HASHTAGS]:
                tag = str(tag).strip().lstrip("#")
                if tag and len(tag) <= MAX_HASHTAG_LEN:
                    tags.append(tag)
            clean["hashtags"] = tags

    return clean, errors


def find_post(posts, post_id):
    """Возвращает (index, post) по id, или (None, None)."""
    for i, post in enumerate(posts):
        if post.get("id") == post_id:
            return i, post
    return None, None


# ---------------------------------------------------------------------------
# API ХРАНИЛИЩА: список / создание / редактирование / удаление
# ---------------------------------------------------------------------------
@app.route("/api/posts", methods=["GET"])
def api_posts_list():
    """Список всех постов (новые сверху)."""
    posts = sorted(load_posts(), key=lambda p: p.get("updated_at", ""), reverse=True)
    return jsonify({"posts": posts})


@app.route("/api/posts", methods=["POST"])
def api_posts_create():
    """Создаёт новый пост."""
    data = request.get_json(silent=True) or {}
    clean, errors = validate_post_payload(data)
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    post = {
        "id": uuid.uuid4().hex,
        "name": clean.get("name") or "Без названия",
        "text": clean["text"],
        "mood": clean.get("mood") or "",
        "mode": str(data.get("mode") or "").strip(),
        "hashtags": clean.get("hashtags", []),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    posts = load_posts()
    posts.append(post)
    save_posts(posts)
    return jsonify({"post": post}), 201


@app.route("/api/posts/<post_id>", methods=["PUT"])
def api_posts_update(post_id):
    """Редактирует пост (имя / текст / настроение / хештеги)."""
    data = request.get_json(silent=True) or {}
    clean, errors = validate_post_payload(data, partial=True)
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    posts = load_posts()
    index, post = find_post(posts, post_id)
    if post is None:
        return jsonify({"error": "Пост не найден"}), 404

    post.update(clean)
    post["updated_at"] = now_iso()
    posts[index] = post
    save_posts(posts)
    return jsonify({"post": post})


@app.route("/api/posts/<post_id>", methods=["DELETE"])
def api_posts_delete(post_id):
    """Удаляет пост."""
    posts = load_posts()
    index, _ = find_post(posts, post_id)
    if index is None:
        return jsonify({"error": "Пост не найден"}), 404

    del posts[index]
    save_posts(posts)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# ПОДБОР ХЕШТЕГОВ
# ---------------------------------------------------------------------------
# Два способа:
#   1. Нейросеть — если в .env есть ключ: модель подбирает релевантные теги.
#   2. Офлайн — если ключа нет или AI ответил ошибкой: берём ключевые слова
#      из текста + базовые теги по настроению. Всё локально, без интернета.
# ---------------------------------------------------------------------------

MAX_HASHTAGS_OUT = 12        # сколько тегов отдаём за раз
MIN_HASHTAG = 2              # слишком короткие слова в теги не превращаем

# Слова, которые не несут темы поста.
STOPWORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а",
    "то", "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же",
    "вы", "за", "бы", "по", "только", "её", "мне", "было", "вот", "от",
    "меня", "еще", "нет", "о", "из", "ему", "теперь", "когда", "даже",
    "ну", "вдруг", "ли", "если", "уже", "или", "ни", "быть", "был", "него",
    "до", "вас", "нибудь", "опять", "уж", "вам", "ведь", "там", "потом",
    "себя", "ничего", "ей", "может", "они", "тут", "где", "есть", "надо",
    "ней", "для", "мы", "тебя", "их", "чем", "была", "сам", "чтоб", "без",
    "будто", "чего", "раз", "тоже", "себе", "под", "будет", "ж", "тогда",
    "кто", "этот", "того", "потому", "этого", "какой", "совсем", "ним",
    "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "сейчас",
    "были", "куда", "зачем", "всех", "никогда", "можно", "при", "наконец",
    "два", "об", "другой", "хоть", "после", "над", "больше", "тот", "через",
    "эти", "нас", "про", "всего", "них", "какая", "много", "разве",
    "эту", "моя", "впрочем", "хорошо", "свою", "этой", "перед", "иногда",
    "лучше", "чуть", "том", "нельзя", "им", "более", "всегда", "конечно",
    "всю", "между", "это", "чтоб", "сам", "мне", "бы",
    "чтобы", "такой", "этих", "всё", "ещё", "всем", "которые",
    "который", "которая", "очень", "вот",
    # часто встречающиеся «водные» слова из описаний
    "товар", "товары", "наш", "наша", "наши", "ваш", "ваша", "ваше",
    "можно", "цена", "цены", "стоит", "руб", "рублей",
    "штук", "штука", "новый", "новая", "новое", "год", "года",
    # глаголы и «вода» из описаний товаров
    "держит", "позволяет", "подходит", "делает", "имеет", "работает",
    "включает", "входит", "нужно", "надо", "хочу", "рассказать",
    "бонус", "такой", "именно", "сейчас", "пока", "наличии", "просто",
    "очень", "уже", "будет", "является", "представляет", "обеспечивает",
    # слова из шаблонов постов — темы товара они не несут
    "выгодная", "сделает", "забирай", "такого", "увидели", "ярче",
    "бонус", "спрашивай", "расскажу", "детали", "призыв", "действия",
    "оформите", "заказ", "связи", "этапе", "надёжное", "решение",
    "задач", "преимущество", "прямо", "сейчас", "привет",
}

# Базовые теги по настроению — добавляются к ключевым словам.
MOOD_BASE_TAGS = {
    "яркий": ["новинка", "яркие", "эмоции"],
    "деловой": ["качество", "надёжность", "выбор"],
    "дружелюбный": ["совет", "рекомендация", "настроение"],
}


def offline_hashtags(text, mood=""):
    """Офлайн-подбор: ключевые слова из текста + база по настроению."""
    words = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", text.lower())

    # Считаем частоту «тематических» слов.
    frequency = {}
    for word in words:
        if word in STOPWORDS or word.isdigit():
            continue
        frequency[word] = frequency.get(word, 0) + 1

    # Чем чаще и длиннее слово — тем оно «тематичнее».
    ranked = sorted(
        frequency.items(),
        key=lambda item: (item[1], len(item[0])),
        reverse=True,
    )

    # Берём теги, отсеивая словоформы одного слова:
    # «кружка» и «кружку» — это один тег, хватит первого.
    tags, taken_prefixes = [], set()
    for word, _ in ranked:
        if len(word) < MIN_HASHTAG:
            continue
        prefix = word[:4]
        if prefix in taken_prefixes:
            continue
        taken_prefixes.add(prefix)
        tags.append(word)

    tags += MOOD_BASE_TAGS.get(mood, [])

    return _clean_hashtags(tags)


def ai_hashtags(text):
    """Подбор тегов нейросетью. Кидает AIGenerationError при проблемах."""
    system = (
        "Ты подбираешь хештеги для поста о товаре в соцсети.\n"
        f"Верни от 3 до {MAX_HASHTAGS_OUT} хештегов строго валидным "
        "JSON-массивом строк, без символа # в начале слов, без пояснений "
        "и без Markdown. Только массив: [\"слово\", \"слово\"].\n"
        "Теги — на языке поста, короткие и по теме."
    )

    result = call_neuro([
        {"role": "system", "content": system},
        {"role": "user", "content": text[:3000]},
    ])

    # Пытаемся вытащить JSON-массив из ответа.
    match = re.search(r"\[[\s\S]*?\]", result)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return _clean_hashtags([str(tag) for tag in data])
        except json.JSONDecodeError:
            pass

    # Запасной путь: ответ вида «#раз, #два».
    return _clean_hashtags(re.findall(r"#?([\wА-Яа-яЁё-]{3,})", result))


def _clean_hashtags(tags):
    """Чистит теги: убирает #, дубликаты (без учёта регистра) и пустоту."""
    clean, seen = [], set()
    for tag in tags:
        tag = str(tag).strip().lstrip("#").strip(".,!?;: ")
        key = tag.lower()
        if len(tag) >= MIN_HASHTAG and key not in seen:
            seen.add(key)
            clean.append(tag)
        if len(clean) >= MAX_HASHTAGS_OUT:
            break
    return clean


@app.route("/api/hashtags", methods=["POST"])
def api_hashtags():
    """
    Подбор хештегов к тексту поста.
    Принимает {text, mood}. Возвращает {hashtags, source},
    source = "ai" (нейросеть) или "offline" (локальный подбор).
    """
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Пустой текст — нечего анализировать"}), 400

    mood = str(data.get("mood") or "").strip()
    tags, source = [], "offline"

    # 1. Пробуем нейросеть (если задан ключ API).
    if AI_API_KEY:
        try:
            tags = ai_hashtags(text)
            source = "ai"
        except AIGenerationError:
            tags = []  # ключ есть, но не ответила — молча уходим в офлайн

    # 2. Офлайн-вариант: без ключа или как запасной.
    if not tags:
        tags = offline_hashtags(text, mood)
        source = "offline"

    return jsonify({"hashtags": tags, "source": source})


# ---------------------------------------------------------------------------
# ПАКЕТНАЯ ГЕНЕРАЦИЯ (список из Excel / CSV / вставки из буфера)
# ---------------------------------------------------------------------------
# Как это работает:
#   1. POST /api/batch/check  — парсит строки, генерирует посты, ищет дубликаты
#      относительно уже сохранённых постов и внутри самого списка.
#   2. Клиент показывает дубликаты в модалке — пользователь отмечает,
#      какие из них загружать.
#   3. POST /api/batch/create — создаёт выбранные посты.
#
# Разделитель колонок определяется автоматически: таб (из Excel) / «;» / «,».
# ---------------------------------------------------------------------------

MAX_BATCH_ROWS = 50          # лимит строк в одном запросе (шаблон)
MAX_BATCH_AI_ROWS = 10       # AI-батч меньше: каждый запрос — деньги и время
DUP_THRESHOLD = 0.85         # порог похожести текстов (0.85 = 85%)
DUP_COMPARE_CHARS = 800      # сравниваем первые N знаков — быстрее и не хуже

# Строки-заголовки, которые не нужно генерировать.
HEADER_NAMES = {"название", "товар", "name", "ссылка", "link", "url"}
HEADER_DESCRIPTIONS = {"описание", "description", "опис", "о товаре"}


def normalize_text(text):
    """Нормализация для сравнения: нижний регистр, без пунктуации и эмодзи."""
    text = text.lower()
    # Убираем эмодзи и всё небуквенное/нечисловое (кроме пробелов).
    text = re.sub(r"[^0-9a-zа-яё\s]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def detect_delimiter(content):
    """Таб из Excel, иначе «;», иначе «,»."""
    first_line = content.splitlines()[0] if content.splitlines() else ""
    if "\t" in first_line:
        return "\t"
    if ";" in first_line:
        return ";"
    return ","


def parse_batch(content, mode, mood_default):
    """
    Разбирает текст списка в строки.
    Возвращает (rows, parse_error):
      rows — [{index, name, link, description, benefit, mood, error}],
      parse_error — строка с ошибкой парсинга или None.
    """
    content = (content or "").strip()
    if not content:
        return [], "Список пуст — вставь строки"

    delimiter = detect_delimiter(content)
    try:
        raw_rows = [
            row for row in csv.reader(io.StringIO(content), delimiter=delimiter)
            if any(cell.strip() for cell in row)
        ]
    except csv.Error as e:
        return [], f"Не получилось разобрать список: {e}"

    # Пропускаем строку-заголовок («Название | Описание | …»).
    if raw_rows:
        first_cells = [cell.strip().lower() for cell in raw_rows[0]]
        if mode == "template" and first_cells and first_cells[0] in HEADER_NAMES:
            if len(first_cells) < 2 or first_cells[1] in HEADER_DESCRIPTIONS:
                raw_rows = raw_rows[1:]
        elif mode == "ai" and first_cells and first_cells[0] in HEADER_NAMES:
            raw_rows = raw_rows[1:]

    if not raw_rows:
        return [], "В списке нет строк с данными"

    rows = []
    for number, cells in enumerate(raw_rows, start=1):
        cells = [cell.strip() for cell in cells]
        row = {"index": number, "mood": mood_default, "error": None}

        if mode == "template":
            row["name"] = cells[0] if len(cells) > 0 else ""
            row["description"] = cells[1] if len(cells) > 1 else ""
            row["benefit"] = cells[2] if len(cells) > 2 else ""
            if len(cells) > 3 and cells[3]:
                row["mood"] = cells[3]

            if not row["description"]:
                row["error"] = "нет описания (обязательная вторая колонка)"
            elif row["mood"] not in MOODS:
                if any(mood.startswith(row["mood"]) for mood in MOODS):
                    # «яркий ✨» или другой вариант написания
                    row["mood"] = next(
                        mood for mood in MOODS if mood.startswith(row["mood"])
                    )
                else:
                    row["mood"] = mood_default
        else:  # ai
            row["link"] = cells[0] if len(cells) > 0 else ""
            if len(cells) > 1 and cells[1]:
                row["mood"] = cells[1]

            if not row["link"]:
                row["error"] = "нет ссылки (обязательная первая колонка)"
            else:
                scheme = urllib.parse.urlparse(row["link"]).scheme.lower()
                if scheme not in ("http", "https"):
                    row["error"] = "ссылка должна начинаться с http:// или https://"
                elif row["mood"] not in MOODS:
                    row["mood"] = mood_default

        rows.append(row)

    if len(rows) > (MAX_BATCH_AI_ROWS if mode == "ai" else MAX_BATCH_ROWS):
        limit = MAX_BATCH_AI_ROWS if mode == "ai" else MAX_BATCH_ROWS
        return [], f"Слишком много строк: {len(rows)}. Лимит — {limit}."

    return rows, None


def generate_batch_rows(rows, mode):
    """Генерирует текст поста для каждой валидной строки. Ошибки — в row['error']."""
    for row in rows:
        if row["error"]:
            continue
        try:
            if mode == "template":
                row["text"] = build_post(
                    row.get("name", ""),
                    row.get("description", ""),
                    row.get("benefit", ""),
                    row.get("mood", "яркий"),
                )
            else:
                page_text = fetch_page_text(row["link"])
                row["text"] = call_neuro(
                    build_ai_messages(row.get("mood", "яркий"), page_text)
                )
                # Название для списка постов AI не знает — берём начало текста.
                if not row.get("name"):
                    row["name"] = (row["text"].split("\n")[0])[:80]
        except AIGenerationError as e:
            row["error"] = str(e)
        except Exception:
            row["error"] = "не удалось сгенерировать пост"

    return rows


def find_batch_duplicates(rows, existing_posts):
    """
    Ищет дубликаты: похожие на уже сохранённые посты и на другие строки списка.
    Возвращает список: {index, name, similarity, target_name, target_date, in_batch}
    """
    existing = [
        (post, normalize_text(post.get("text", ""))[:DUP_COMPARE_CHARS])
        for post in existing_posts
    ]

    duplicates, seen = [], {}

    for row in rows:
        if row.get("error") or not row.get("text"):
            continue

        normalized = normalize_text(row["text"])[:DUP_COMPARE_CHARS]
        if not normalized:
            continue

        # 1. Точное совпадение с сохранённым постом.
        match, similarity = None, 0.0
        for post, existing_norm in existing:
            if not existing_norm:
                continue
            if normalized == existing_norm:
                match, similarity = post, 1.0
                break
            # Быстрая отбраковка: если даже грубая оценка мала — не считаем.
            matcher = difflib.SequenceMatcher(None, normalized, existing_norm)
            if matcher.real_quick_ratio() < DUP_THRESHOLD:
                continue
            ratio = matcher.ratio()
            if ratio >= DUP_THRESHOLD and ratio > similarity:
                match, similarity = post, ratio

        if match:
            duplicates.append({
                "index": row["index"],
                "name": row.get("name") or row.get("link", ""),
                "similarity": round(similarity * 100),
                "target_name": match.get("name", "без названия"),
                "target_date": match.get("created_at", ""),
                "in_batch": False,
            })
            row["duplicate"] = True
            continue

        # 2. Дубликат внутри самого списка (вторая и далее идентичные строки).
        if normalized in seen:
            duplicates.append({
                "index": row["index"],
                "name": row.get("name") or row.get("link", ""),
                "similarity": 100,
                "target_name": f"строка {seen[normalized]} этого же списка",
                "target_date": "",
                "in_batch": True,
            })
            row["duplicate"] = True
        else:
            seen[normalized] = row["index"]

    return duplicates


@app.route("/api/batch/check", methods=["POST"])
def api_batch_check():
    """
    Парсит список, генерирует посты и ищет дубликаты.
    Возвращает {rows, duplicates, total, valid, errors}.
    """
    data = request.get_json(silent=True) or {}
    content = str(data.get("content") or "")
    mode = str(data.get("mode") or "template").strip()
    mood_default = str(data.get("mood_default") or "").strip() or "яркий"

    if mode not in ("template", "ai"):
        return jsonify({"error": "Неизвестный режим"}), 400
    if mood_default not in MOODS:
        return jsonify({"error": "Неизвестное настроение"}), 400

    # AI-батч требует ключа — проверяем заранее, а не на третьей строке.
    if mode == "ai" and not AI_API_KEY:
        return jsonify({
            "error": "Для пакетной генерации нейросетью нужен ключ API в файле .env"
        }), 400

    rows, parse_error = parse_batch(content, mode, mood_default)
    if parse_error:
        return jsonify({"error": parse_error}), 400

    generate_batch_rows(rows, mode)
    duplicates = find_batch_duplicates(rows, load_posts())

    valid = [row for row in rows if not row.get("error")]
    invalid = [row for row in rows if row.get("error")]

    return jsonify({
        "rows": [{
            "index": row["index"],
            "name": row.get("name", ""),
            "mood": row.get("mood", ""),
            "text": row.get("text", ""),
            "error": row.get("error"),
            "duplicate": bool(row.get("duplicate")),
        } for row in rows],
        "duplicates": duplicates,
        "total": len(rows),
        "valid": len(valid),
        "errors": len(invalid),
    })


@app.route("/api/batch/create", methods=["POST"])
def api_batch_create():
    """Создаёт посты из проверенного списка (после подтверждения дубликатов)."""
    data = request.get_json(silent=True) or {}
    items = data.get("items")

    if not isinstance(items, list) or not items:
        return jsonify({"error": "Пустой список"}), 400
    if len(items) > MAX_BATCH_ROWS:
        return jsonify({"error": f"Лимит — {MAX_BATCH_ROWS} постов за раз"}), 400

    posts = load_posts()
    created, errors = [], []

    for number, item in enumerate(items, start=1):
        clean, item_errors = validate_post_payload(item)
        if item_errors:
            errors.append({
                "index": item.get("index", number),
                "name": item.get("name", ""),
                "error": "; ".join(item_errors),
            })
            continue

        posts.append({
            "id": uuid.uuid4().hex,
            "name": clean.get("name") or "Без названия",
            "text": clean["text"],
            "mood": clean.get("mood") or "",
            "mode": str(item.get("mode") or "template"),
            "hashtags": clean.get("hashtags", []),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        created.append(item.get("index", number))

    save_posts(posts)
    return jsonify({"created": len(created), "errors": errors})


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

    # Падеж подстановки названия: "" = авто (по шаблону), иначе — один из CASES.
    name_case = (data.get("name_case") or "").strip()
    if name_case and name_case not in CASES:
        return jsonify({"error": "Неизвестный падеж"}), 400

    # Собираем текст поста.
    post = build_post(name, description, benefit, mood, name_case)

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