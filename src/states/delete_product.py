from aiogram.fsm.state import State, StatesGroup


class DeleteProduct(StatesGroup):
    waiting_model = State()
    waiting_confirm = State()
