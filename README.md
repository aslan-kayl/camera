# Telegram Price Bot

Проект для импорта прайс-листа из Excel в PostgreSQL и поиска товаров по модели.

Стек: Python 3.12+, aiogram 3, PostgreSQL, SQLAlchemy 2 async, pandas, openpyxl, Docker Compose.

## Структура проекта

```text
.
├── bot.py              # Telegram-бот и поиск товаров
├── db.py               # async SQLAlchemy engine/session
├── import_excel.py     # импорт Excel в PostgreSQL
├── models.py           # SQLAlchemy модель Product
├── services/
│   ├── ocr_service.py      # OCR, preprocessing, извлечение моделей
│   └── product_service.py  # поиск exact/partial/fuzzy
├── utils/
│   └── normalize.py        # нормализация модели и парсинг значений
├── docker-compose.yml  # PostgreSQL
├── requirements.txt
├── .env.example
└── data/
```

## Модель данных

Таблица `products`:

- `id`
- `model`
- `normalized_model`
- `description`
- `price`
- `stock`
- `image_path`
- `created_at`

`normalized_model` генерируется из `model`: строка переводится в uppercase, пробелы, дефисы и другие не буквенно-цифровые символы удаляются.

Пример:

```text
DS-7108NI-Q1 -> DS7108NIQ1
```

## Формат Excel

Файл должен содержать колонки:

- `Наименование`
- `Изображение`
- `Описание`
- `Цена`

Также поддерживаются альтернативные названия колонок:

- модель: `Наименование`, `Модель`, `Model`, `IMOU Model`, `Артикул`, `SKU`, `Код`;
- фото: `Изображение`, `Фото`, `Photo`, `Image`, `Image Path`, `Картинка`;
- описание: `Описание`, `Description`, `Desc`, `Характеристики`;
- цена: `Цена`, `Price`, `Стоимость`, `Прайс`.

Если `Изображение` пустое, в БД сохраняется `NULL`.

Импорт также умеет читать файл, где строка с этими заголовками находится не в заголовке pandas, а первой строкой таблицы.

## Быстрый старт

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres
```

По умолчанию PostgreSQL публикуется на `localhost:5433`, чтобы не конфликтовать с уже запущенным локальным PostgreSQL на `5432`.

`.env.example`:

```env
BOT_TOKEN=change-me
DATABASE_URL=postgresql+asyncpg://price:price@localhost:5433/price
LOG_LEVEL=INFO
ADMIN_IDS=
```

`ADMIN_IDS` - список Telegram user id через запятую. Если оставить пустым, загрузка Excel доступна всем. Для production лучше указать только администраторов:

```env
ADMIN_IDS=123456789,987654321
```

## Импорт Excel

```bash
.venv/bin/python import_excel.py "data/DARIAN HIKVISION PRICE (8).xlsx"
```

Если нужно пересоздать таблицу `products`:

```bash
.venv/bin/python import_excel.py "data/DARIAN HIKVISION PRICE (8).xlsx" --recreate
```

## Поиск

Поиск работает по `normalized_model` через partial match:

```sql
WHERE normalized_model ILIKE '%7108%'
```

Для `normalized_model` созданы индексы:

- обычный btree индекс `ix_products_normalized_model`;
- trigram GIN индекс `ix_products_normalized_model_trgm` для ускорения `ILIKE '%...%'`.

Пример: запрос `7108` находит `DS-7108NI-Q1`.

## Запуск бота

Укажите реальный `BOT_TOKEN` в `.env`, затем:

```bash
.venv/bin/python bot.py
```

Пользователь отправляет модель или часть модели, например `7108`, бот ищет товар в PostgreSQL и возвращает модель, цену, описание и изображение, если путь или URL есть в Excel.

Также пользователь может отправить фото этикетки товара. Бот:

1. скачает фото в `data/ocr_uploads/`;
2. подготовит изображение через OpenCV;
3. запустит EasyOCR;
4. выделит кандидаты моделей вроде `DS-2CD2043G2-I`, `DHI-XVR5108HS-I3`, `IPC-A22EP`, `DH-IPC-HDW1230T1`;
5. нормализует кандидаты;
6. сначала попробует точный поиск по `normalized_model`;
7. если точного совпадения нет, выполнит fuzzy search через `rapidfuzz`;
8. вернет модель, описание, цену и остаток. Если остаток не был загружен из Excel, будет показано `не указан`.

В боте есть кнопки:

- `Поиск товара` - перейти к поиску по модели;
- `Загрузить Excel` - загрузить новый прайс-лист в БД.

Чтобы обновить товары через Telegram:

1. Нажмите `Загрузить Excel`.
2. Отправьте файл документом в формате `.xlsx` или `.xlsm`.
3. Бот скачает файл, импортирует товары и обновит существующие позиции по `normalized_model`.

Фото товара выводится из колонки `Изображение`. Значение может быть:

- URL: `https://example.com/image.jpg`;
- локальный путь к файлу относительно папки проекта: `data/images/model.jpg`;
- пустая ячейка - бот отправит только текст.

Если в Excel картинка вставлена прямо в колонку `Изображение` как embedded image, импорт извлечет файл в `data/product_images/` и сохранит этот путь в `image_path`.

Если по запросу найдено несколько товаров, бот отправит каждый найденный результат отдельным сообщением.

## OCR

OCR-зависимости:

- `easyocr`
- `opencv-python`
- `Pillow`
- `rapidfuzz`
- CPU-only `torch` и `torchvision`

В `requirements.txt` указан PyTorch CPU index, чтобы не скачивать CUDA-пакеты на сервер без GPU.

## Проверка состояния БД

```bash
docker compose ps
```

Контейнер должен быть `healthy`.
