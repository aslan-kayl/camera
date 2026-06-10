from aiogram.fsm.state import State, StatesGroup


class AddUser(StatesGroup):
    waiting_role = State()
