from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from services.user_service import ROLE_SUPER_ADMIN, ROLE_USER

SEARCH_BUTTON = "Поиск товара"
UPLOAD_EXCEL_BUTTON = "Загрузить Excel"
ADD_PRODUCT_BUTTON = "➕ Добавить товар"
DELETE_PRODUCT_BUTTON = "🗑 Удалить товар"
UPDATE_PRODUCT_BUTTON = "✏️ Обновить товар"
ADD_USER_BUTTON = "👤 Добавить пользователя"
DELETE_USER_BUTTON = "🚫 Удалить пользователя"
ROLE_USER_CHOICE_BUTTON = "Обычный пользователь"
ROLE_ADMIN_CHOICE_BUTTON = "Администратор"
BACK_BUTTON = "⬅️ Назад"
DELETE_USER_YES_BUTTON = "✅ Да"
DELETE_USER_NO_BUTTON = "❌ Нет"
CANCEL_BUTTON = "❌ Отмена"
DELETE_CONFIRM_BUTTON = "✅ Удалить"
UPDATE_PHOTO_BUTTON = "🖼 Обновить фото"
UPDATE_MODEL_BUTTON = "🔤 Обновить модель"
UPDATE_PRICE_BUTTON = "💰 Обновить цену"
UPDATE_DESCRIPTION_BUTTON = "📝 Обновить описание"
CONTINUE_UPDATE_BUTTON = "🔄 Продолжить обновление"
MAIN_MENU_BUTTON = "🏠 Главное меню"
SKIP_BUTTON = "⏭ Пропустить"


def _btn(text: str) -> KeyboardButton:
    return KeyboardButton(text=text)


def main_keyboard(is_admin: bool = True, is_super_admin: bool = False) -> ReplyKeyboardMarkup:
    # USERs may only search/view, so admin-only buttons are hidden for them.
    # Admin actions are packed two per row to keep the keyboard compact.
    keyboard = [[_btn(SEARCH_BUTTON)]]
    if is_admin or is_super_admin:
        keyboard += [
            [_btn(ADD_PRODUCT_BUTTON), _btn(UPDATE_PRODUCT_BUTTON)],
            [_btn(DELETE_PRODUCT_BUTTON), _btn(UPLOAD_EXCEL_BUTTON)],
        ]
    if is_super_admin:
        keyboard += [[_btn(ADD_USER_BUTTON), _btn(DELETE_USER_BUTTON)]]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Введите название, модель или часть названия",
    )


def main_keyboard_for_role(role: str | None) -> ReplyKeyboardMarkup:
    """Main menu tailored to a role string (None defaults to the admin menu)."""
    return main_keyboard(
        is_admin=role != ROLE_USER,
        is_super_admin=role == ROLE_SUPER_ADMIN,
    )


def add_user_role_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_btn(ROLE_USER_CHOICE_BUTTON), _btn(ROLE_ADMIN_CHOICE_BUTTON)],
            [_btn(BACK_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Кого добавить — пользователя или админа?",
    )


def delete_user_role_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_btn(ROLE_USER_CHOICE_BUTTON), _btn(ROLE_ADMIN_CHOICE_BUTTON)],
            [_btn(BACK_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Кого удалить — пользователя или админа?",
    )


def users_list_keyboard(labels: list[str]) -> ReplyKeyboardMarkup:
    # One selectable user per row, with Back at the bottom.
    keyboard = [[_btn(label)] for label in labels]
    keyboard.append([_btn(BACK_BUTTON)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите пользователя или нажмите «Назад»",
    )


def delete_user_confirm_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[_btn(DELETE_USER_YES_BUTTON), _btn(DELETE_USER_NO_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Подтвердите удаление",
    )


def update_field_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_btn(UPDATE_PHOTO_BUTTON), _btn(UPDATE_MODEL_BUTTON)],
            [_btn(UPDATE_DESCRIPTION_BUTTON), _btn(UPDATE_PRICE_BUTTON)],
            [_btn(CANCEL_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите, что обновить, или нажмите Отмена",
    )


def description_keyboard() -> ReplyKeyboardMarkup:
    # Description is optional, so the user can skip it (stored as empty).
    return ReplyKeyboardMarkup(
        keyboard=[[_btn(SKIP_BUTTON), _btn(CANCEL_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Введите описание или нажмите «Пропустить»",
    )


def confirm_delete_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[_btn(DELETE_CONFIRM_BUTTON), _btn(CANCEL_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Подтвердите удаление или нажмите Отмена",
    )


def update_next_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[_btn(CONTINUE_UPDATE_BUTTON), _btn(MAIN_MENU_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Продолжить обновление или перейти в главное меню",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[_btn(CANCEL_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="Заполните данные товара или нажмите Отмена",
    )
