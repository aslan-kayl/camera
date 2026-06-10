from aiogram.fsm.state import State, StatesGroup


class DeleteUser(StatesGroup):
    waiting_role = State()
    waiting_user = State()
    waiting_confirm = State()
