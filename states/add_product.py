from aiogram.fsm.state import State, StatesGroup


class AddProduct(StatesGroup):
    waiting_model = State()
    waiting_photo = State()
    waiting_description = State()
    waiting_price = State()
