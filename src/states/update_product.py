from aiogram.fsm.state import State, StatesGroup


class UpdateProduct(StatesGroup):
    waiting_model = State()
    waiting_field = State()
    waiting_photo = State()
    waiting_new_model = State()
    waiting_description = State()
    waiting_price = State()
    waiting_next = State()
