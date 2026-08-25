from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app.config import load_config
from app.db import Database


class Register(StatesGroup):
    city = State()


class AddReview(StatesGroup):
    platform = State()
    client_name = State()
    office = State()
    proof = State()


config = load_config()
db = Database(config.database_path)
router = Router()


CITIES = ["Москва", "Санкт-Петербург", "Псков", "Великий Новгород", "Другой"]
PLATFORMS = ["Яндекс", "2ГИС", "Google", "Avito", "Другое"]
MENU_ADD = "📝 Отправить отзыв"
MENU_KPI = "📊 Мой KPI"
MENU_CITY = "🏙 Сменить город"
MENU_HELP = "❔ Помощь"


def keyboard(items: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=item)] for item in items],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu(is_admin_user: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=MENU_ADD), KeyboardButton(text=MENU_KPI)],
        [KeyboardButton(text=MENU_CITY), KeyboardButton(text=MENU_HELP)],
    ]
    if is_admin_user:
        rows.append([KeyboardButton(text="🕓 На проверке"), KeyboardButton(text="📋 Отчет")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def show_main_menu(message: Message, text: str | None = None) -> None:
    await message.answer(
        text
        or "Готово. Выбери действие кнопкой ниже.",
        reply_markup=main_menu(is_admin(message)),
    )


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in config.admin_ids)


@router.message(StateFilter("*"), Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    manager = db.get_manager(message.from_user.id)
    if manager:
        await show_main_menu(
            message,
            f"Ты уже привязан к городу: {manager.city}\n\n"
            "Дальше просто нажимай кнопки внизу."
        )
        return

    await state.set_state(Register.city)
    await message.answer("Выбери город, к которому тебя привязать:", reply_markup=keyboard(CITIES))


@router.message(StateFilter("*"), Command("city"))
@router.message(StateFilter("*"), F.text == MENU_CITY)
async def change_city(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Register.city)
    await message.answer("Выбери город:", reply_markup=keyboard(CITIES))


@router.message(Register.city)
async def save_city(message: Message, state: FSMContext) -> None:
    await register_manager_city(message, state)


async def register_manager_city(message: Message, state: FSMContext) -> None:
    name = message.from_user.full_name if message.from_user else "Без имени"
    db.upsert_manager(message.from_user.id, name, message.text.strip())
    await state.clear()
    await show_main_menu(
        message,
        "Город сохранен.\n\n"
        "Теперь можно отправлять отзывы и смотреть KPI кнопками внизу."
    )


@router.message(StateFilter("*"), Command("add"))
@router.message(StateFilter("*"), F.text == MENU_ADD)
async def add_review(message: Message, state: FSMContext) -> None:
    await state.clear()
    manager = db.get_manager(message.from_user.id)
    if not manager:
        await state.set_state(Register.city)
        await message.answer("Сначала выбери город:", reply_markup=keyboard(CITIES))
        return

    await state.set_state(AddReview.office)
    await message.answer(
        "Напиши точку/офис, как сейчас пишете в группе. Например: СЦ Авиамоторная"
    )


@router.message(AddReview.office)
async def save_office(message: Message, state: FSMContext) -> None:
    await state.update_data(office=message.text.strip())
    await state.set_state(AddReview.platform)
    await message.answer("Где опубликован/будет опубликован отзыв?", reply_markup=keyboard(PLATFORMS))


@router.message(AddReview.platform)
async def save_platform(message: Message, state: FSMContext) -> None:
    await state.update_data(platform=message.text.strip())
    await state.set_state(AddReview.client_name)
    await message.answer("Имя клиента, ник или короткая пометка. Если не знаешь, напиши '-'")


@router.message(AddReview.client_name)
async def save_client_name(message: Message, state: FSMContext) -> None:
    await state.update_data(client_name=message.text.strip())
    await state.set_state(AddReview.proof)
    await message.answer(
        "Теперь отправь доказательство: фото/скрин отзыва или текст/ссылку. "
        "Можно фото с подписью.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddReview.proof)
async def save_review(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    attachment_file_id = message.photo[-1].file_id if message.photo else None
    proof_text = message.caption or message.text or "Фото без подписи"
    review_id = db.add_review(
        manager_id=message.from_user.id,
        platform=data["platform"],
        client_name=data["client_name"],
        review_text=f"Точка: {data['office']}\nДоказательство: {proof_text.strip()}",
        attachment_file_id=attachment_file_id,
        price=config.default_review_price,
    )
    await state.clear()

    await message.answer(
        f"Отзыв #{review_id} принят на проверку.\n"
        f"Сумма после подтверждения: {config.default_review_price} руб.",
        reply_markup=main_menu(is_admin(message)),
    )

    admin_text = (
        f"Новый отзыв #{review_id}\n"
        f"Менеджер: {message.from_user.full_name} ({message.from_user.id})\n"
        f"Точка: {data['office']}\n"
        f"Платформа: {data['platform']}\n"
        f"Клиент: {data['client_name']}\n"
        f"Доказательство: {proof_text.strip()}\n\n"
        f"Подтвердить: /approve_{review_id}\n"
        f"Отклонить: /reject_{review_id}"
    )
    for admin_id in config.admin_ids:
        if attachment_file_id:
            await bot.send_photo(admin_id, attachment_file_id, caption=admin_text)
        else:
            await bot.send_message(admin_id, admin_text)


@router.message(StateFilter("*"), Command("kpi"))
@router.message(StateFilter("*"), F.text == MENU_KPI)
async def kpi(message: Message) -> None:
    rows = db.get_stats(message.from_user.id)
    if not rows:
        await message.answer("Ты еще не привязан к городу. Нажми /start.")
        return

    row = rows[0]
    await message.answer(
        f"KPI по менеджеру: {row['name']}\n"
        f"Город: {row['city']}\n"
        f"Всего отправлено: {row['total_reviews']}\n"
        f"На проверке: {row['pending_reviews']}\n"
        f"Подтверждено: {row['approved_reviews']}\n"
        f"Заработано: {row['earned']} руб."
    )


@router.message(StateFilter("*"), Command("pending"))
@router.message(StateFilter("*"), F.text == "🕓 На проверке")
async def pending(message: Message) -> None:
    if not is_admin(message):
        await message.answer("Команда доступна только администратору.")
        return

    rows = db.list_pending_reviews()
    if not rows:
        await message.answer("Нет отзывов на проверке.")
        return

    text = "\n\n".join(
        f"#{row['id']} | {row['name']} | {row['city']} | {row['platform']}\n"
        f"{row['review_text']}\n"
        f"/approve_{row['id']} или /reject_{row['id']}"
        for row in rows
    )
    await message.answer(text)


@router.message(StateFilter("*"), Command("report"))
@router.message(StateFilter("*"), F.text == "📋 Отчет")
async def report(message: Message) -> None:
    if not is_admin(message):
        await message.answer("Команда доступна только администратору.")
        return

    rows = db.get_stats()
    if not rows:
        await message.answer("Пока нет менеджеров.")
        return

    text = "Отчет по менеджерам:\n\n" + "\n".join(
        f"{row['name']} | {row['city']} | "
        f"подтв.: {row['approved_reviews']} | "
        f"проверка: {row['pending_reviews']} | "
        f"{row['earned']} руб."
        for row in rows
    )
    await message.answer(text)


@router.message(StateFilter("*"), F.text.regexp(r"^/approve_\d+$"))
async def approve(message: Message) -> None:
    if not is_admin(message):
        await message.answer("Команда доступна только администратору.")
        return

    review_id = int(message.text.rsplit("_", 1)[1])
    if db.set_review_status(review_id, "approved"):
        await message.answer(f"Отзыв #{review_id} подтвержден.")
    else:
        await message.answer(f"Отзыв #{review_id} не найден.")


@router.message(StateFilter("*"), F.text.regexp(r"^/reject_\d+$"))
async def reject(message: Message) -> None:
    if not is_admin(message):
        await message.answer("Команда доступна только администратору.")
        return

    review_id = int(message.text.rsplit("_", 1)[1])
    if db.set_review_status(review_id, "rejected"):
        await message.answer(f"Отзыв #{review_id} отклонен.")
    else:
        await message.answer(f"Отзыв #{review_id} не найден.")


@router.message(StateFilter("*"), F.text == MENU_HELP)
async def help_menu(message: Message) -> None:
    await show_main_menu(
        message,
        "Что можно делать:\n\n"
        "📝 Отправить отзыв - пройти заявку по шагам\n"
        "📊 Мой KPI - посмотреть подтвержденные отзывы и заработок\n"
        "🏙 Сменить город - заново выбрать город\n\n"
        "Писать команды вручную больше не нужно."
    )


@router.message(F.text.in_(CITIES))
async def save_city_without_state(message: Message, state: FSMContext) -> None:
    manager = db.get_manager(message.from_user.id)
    if manager:
        await show_main_menu(
            message,
            f"Ты уже привязан к городу: {manager.city}.\n"
            f"Чтобы сменить город, нажми «{MENU_CITY}»."
        )
        return

    await register_manager_city(message, state)


@router.message()
async def fallback(message: Message) -> None:
    manager = db.get_manager(message.from_user.id)
    if manager:
        await show_main_menu(message, "Не понял сообщение. Выбери действие кнопкой ниже.")
    else:
        await message.answer("Сначала выбери город через /start.")


async def main() -> None:
    db.init()
    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
