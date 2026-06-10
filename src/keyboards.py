from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

SEARCH_BUTTON = "Поиск товара"
UPLOAD_EXCEL_BUTTON = "Загрузить Excel"
ADD_PRODUCT_BUTTON = "➕ Добавить товар"
DELETE_PRODUCT_BUTTON = "🗑 Удалить товар"
UPDATE_PRODUCT_BUTTON = "✏️ Обновить товар"
CANCEL_BUTTON = "❌ Отмена"
DELETE_CONFIRM_BUTTON = "✅ Удалить"
UPDATE_PHOTO_BUTTON = "🖼 Обновить фото"
UPDATE_MODEL_BUTTON = "🔤 Обновить модель"
UPDATE_PRICE_BUTTON = "💰 Обновить цену"
UPDATE_DESCRIPTION_BUTTON = "📝 Обновить описание"
CONTINUE_UPDATE_BUTTON = "🔄 Продолжить обновление"
MAIN_MENU_BUTTON = "🏠 Главное меню"
SKIP_BUTTON = "⏭ Пропустить"


def main_keyboard(is_admin: bool = True) -> ReplyKeyboardMarkup:
    # USERs may only search/view, so admin-only buttons are hidden for them.
    keyboard = [[KeyboardButton(text=SEARCH_BUTTON)]]
    if is_admin:
        keyboard += [
            [KeyboardButton(text=UPLOAD_EXCEL_BUTTON)],
            [KeyboardButton(text=ADD_PRODUCT_BUTTON)],
            [KeyboardButton(text=DELETE_PRODUCT_BUTTON)],
            [KeyboardButton(text=UPDATE_PRODUCT_BUTTON)],
        ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Введите название, модель или часть названия",
    )


def update_field_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=UPDATE_PHOTO_BUTTON)],
            [KeyboardButton(text=UPDATE_MODEL_BUTTON)],
            [KeyboardButton(text=UPDATE_DESCRIPTION_BUTTON)],
            [KeyboardButton(text=UPDATE_PRICE_BUTTON)],
            [KeyboardButton(text=CANCEL_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите, что обновить, или нажмите Отмена",
    )


def description_keyboard() -> ReplyKeyboardMarkup:
    # Description is optional, so the user can skip it (stored as empty).
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=SKIP_BUTTON)], [KeyboardButton(text=CANCEL_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Введите описание или нажмите «Пропустить»",
    )


def confirm_delete_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=DELETE_CONFIRM_BUTTON)], [KeyboardButton(text=CANCEL_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Подтвердите удаление или нажмите Отмена",
    )


def update_next_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CONTINUE_UPDATE_BUTTON)],
            [KeyboardButton(text=MAIN_MENU_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Продолжить обновление или перейти в главное меню",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Заполните данные товара или нажмите Отмена",
    )
