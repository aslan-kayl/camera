from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

UPLOAD_EXCEL_BUTTON = "Загрузить Excel"
ADD_PRODUCT_BUTTON = "➕ Добавить товар"


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=UPLOAD_EXCEL_BUTTON)],
            [KeyboardButton(text=ADD_PRODUCT_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Введите название, модель или часть названия",
    )
