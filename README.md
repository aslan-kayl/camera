# 📦 Telegram Price Bot

Телеграм-бот для импорта прайс-листа из Excel в PostgreSQL и поиска товаров —
по тексту, по фото этикетки (OCR) и голосом.

**Стек:** Python 3.12+ · [aiogram 3](https://docs.aiogram.dev/) · PostgreSQL 16 ·
SQLAlchemy 2 (async) · pandas · openpyxl · EasyOCR · Docker Compose

---

## ✨ Возможности

- 🔍 **Поиск по тексту** — точное / частичное / fuzzy-совпадение по `normalized_model`.
- 📷 **Поиск по фото** — распознавание модели на этикетке через EasyOCR.
- 🎙️ **Поиск голосом** — транскрипция и извлечение модели из голосового сообщения.
- 📊 **Импорт Excel** — загрузка прайс-листа через Telegram или из командной строки,
  с извлечением встроенных в ячейки картинок.
- ➕ **Добавление товара** — пошаговый сценарий добавления позиции прямо в боте.
- 🧾 **Сметы** — подбор товаров и подсчёт суммы по списку позиций.

---

## 🗂️ Структура проекта

```text
.
├── src/                         # весь исходный код
│   ├── bot.py                   # точка входа: Telegram-бот и роутинг
│   ├── db.py                    # async SQLAlchemy engine / session
│   ├── models.py                # SQLAlchemy-модель Product
│   ├── keyboards.py             # клавиатуры бота
│   ├── import_excel.py          # импорт прайс-листа из Excel в PostgreSQL
│   ├── handlers/                # обработчики Telegram-сообщений
│   │   ├── search.py            #   поиск товаров
│   │   └── add_product.py       #   пошаговое добавление товара
│   ├── services/                # бизнес-логика
│   │   ├── product_service.py   #   поиск exact / partial / fuzzy
│   │   ├── ocr_service.py       #   OCR и извлечение моделей из текста
│   │   ├── image_preprocessing.py #  подготовка изображения (OpenCV)
│   │   ├── image_service.py     #   сохранение фото товара
│   │   ├── voice_service.py     #   распознавание моделей из голоса
│   │   ├── estimate_service.py  #   формирование сметы
│   │   └── temp_file_service.py #   временные файлы фото из поиска
│   ├── states/                  # FSM-состояния aiogram
│   └── utils/                   # нормализация, парсинг, форматирование
├── data/                        # загруженные файлы и изображения (gitignored)
├── docker-compose.yml           # PostgreSQL
├── requirements.txt
├── .env.example
└── README.md
```

> Весь Python-код собран в `src/`. Команды запускаются **из корня проекта**,
> чтобы относительные пути к `data/` и `temp/` разрешались корректно.

---

## 🚀 Быстрый старт

```bash
# 1. Зависимости
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Конфигурация
cp .env.example .env        # затем впишите реальный BOT_TOKEN

# 3. База данных
docker compose up -d postgres

# 4. Запуск бота
.venv/bin/python src/bot.py
```

PostgreSQL публикуется на `localhost:5433`, чтобы не конфликтовать с локальным
PostgreSQL на `5432`. Проверить состояние контейнера (должен быть `healthy`):

```bash
docker compose ps
```

---

## ⚙️ Конфигурация (`.env`)

```env
BOT_TOKEN=change-me
DATABASE_URL=postgresql+asyncpg://price:price@localhost:5433/price
LOG_LEVEL=INFO
ADMIN_IDS=
```

| Переменная     | Назначение                                                                 |
| -------------- | -------------------------------------------------------------------------- |
| `BOT_TOKEN`    | Токен бота из [@BotFather](https://t.me/BotFather).                        |
| `DATABASE_URL` | Строка подключения asyncpg к PostgreSQL.                                    |
| `LOG_LEVEL`    | Уровень логирования (`INFO`, `DEBUG`, …).                                   |
| `ADMIN_IDS`    | Telegram user id через запятую. Пусто → загрузка Excel доступна всем.       |

Для production укажите только администраторов:

```env
ADMIN_IDS=123456789,987654321
```

---

## 🗃️ Модель данных

Таблица `products`:

| Поле               | Описание                                                       |
| ------------------ | -------------------------------------------------------------- |
| `id`               | Первичный ключ.                                                |
| `model`            | Исходное наименование/модель из прайса.                        |
| `normalized_model` | Нормализованная модель (уникальный ключ поиска).               |
| `description`      | Описание / характеристики.                                     |
| `price`            | Цена.                                                          |
| `stock`            | Остаток (если был в Excel, иначе `не указан`).                 |
| `image_path`       | Путь к файлу или URL изображения.                              |
| `created_at`       | Дата создания записи.                                          |

`normalized_model` строится из `model`: строка переводится в верхний регистр,
а пробелы, дефисы и прочие не буквенно-цифровые символы удаляются:

```text
DS-7108NI-Q1  →  DS7108NIQ1
```

Для `normalized_model` созданы два индекса:

- btree `ix_products_normalized_model` — точные совпадения;
- trigram GIN `ix_products_normalized_model_trgm` — ускорение `ILIKE '%...%'`.

---

## 📊 Импорт Excel

### Из командной строки

```bash
.venv/bin/python src/import_excel.py "data/DARIAN HIKVISION PRICE (8).xlsx"

# пересоздать таблицу products перед импортом:
.venv/bin/python src/import_excel.py "data/DARIAN HIKVISION PRICE (8).xlsx" --recreate
```

### Через Telegram

1. Нажмите **«Загрузить Excel»** (доступно администраторам из `ADMIN_IDS`).
2. Отправьте файл документом в формате `.xlsx` или `.xlsm`.
3. Бот импортирует товары и обновит существующие позиции по `normalized_model`.

### Формат файла

Поддерживаемые названия колонок:

| Поле      | Варианты заголовка                                              |
| --------- | -------------------------------------------------------------- |
| Модель    | `Наименование`, `Модель`, `Model`, `IMOU Model`, `Артикул`, `SKU`, `Код` |
| Фото      | `Изображение`, `Фото`, `Photo`, `Image`, `Image Path`, `Картинка` |
| Описание  | `Описание`, `Description`, `Desc`, `Характеристики`            |
| Цена      | `Цена`, `Price`, `Стоимость`, `Прайс`                          |

- Если ячейка `Изображение` пустая → в БД пишется `NULL`.
- Если картинка вставлена в ячейку как embedded image, импорт извлекает её
  в `data/product_images/` и сохраняет путь в `image_path`.
- Импорт умеет читать файлы, где строка заголовков идёт не первой.

---

## 🔍 Поиск

| Способ      | Как работает                                                              |
| ----------- | ------------------------------------------------------------------------- |
| **Текст**   | Частичное совпадение по `normalized_model` (`ILIKE '%7108%'`), затем fuzzy. |
| **Фото**    | Скачивание → препроцессинг (OpenCV) → EasyOCR → выделение и нормализация моделей → exact, затем fuzzy через `rapidfuzz`. |
| **Голос**   | Транскрипция аудио → извлечение кандидатов моделей → поиск по базе.        |

Пример: запрос `7108` находит `DS-7108NI-Q1`. Если найдено несколько товаров,
бот отправит каждый результат отдельным сообщением с моделью, ценой, остатком,
описанием и фото (если оно есть).

Изображение берётся из колонки `Изображение` и может быть:

- URL — `https://example.com/image.jpg`;
- локальный путь относительно корня проекта — `data/images/model.jpg`;
- пустой ячейкой — тогда бот отправит только текст.

---

## 🧠 OCR

OCR-зависимости: `easyocr`, `opencv-python`, `Pillow`, `rapidfuzz`,
а также CPU-сборки `torch` и `torchvision`. В `requirements.txt` указан
PyTorch CPU index — чтобы не тянуть CUDA-пакеты на сервер без GPU.

Бот распознаёт модели вида `DS-2CD2043G2-I`, `DHI-XVR5108HS-I3`,
`IPC-A22EP`, `DH-IPC-HDW1230T1`.
