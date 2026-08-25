import json
import time
import urllib.request

from app.config import load_config
from app.db import Database


config = load_config()
db = Database(config.database_path)

CITIES = ["Москва", "Санкт-Петербург", "Псков", "Великий Новгород", "Другой"]
PLATFORMS = ["Яндекс", "2ГИС", "Google", "Avito", "Другое"]

MENU_ADD = "Отправить отзыв"
MENU_KPI = "Мой KPI"
MENU_CITY = "Сменить город"
MENU_HELP = "Помощь"
ADMIN_PENDING = "На проверке"
ADMIN_REPORT = "Отчет"


def api(method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{config.bot_token}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def send_message(chat_id: int, text: str, keyboard: list[list[str]] | None = None, remove_keyboard: bool = False) -> None:
    payload: dict = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {
            "keyboard": [[{"text": item} for item in row] for row in keyboard],
            "resize_keyboard": True,
        }
    if remove_keyboard:
        payload["reply_markup"] = {"remove_keyboard": True}
    api("sendMessage", payload)


def send_photo(chat_id: int, file_id: str, caption: str) -> None:
    api("sendPhoto", {"chat_id": chat_id, "photo": file_id, "caption": caption})


def main_menu(user_id: int) -> list[list[str]]:
    rows = [[MENU_ADD, MENU_KPI], [MENU_CITY, MENU_HELP]]
    if user_id in config.admin_ids:
        rows.append([ADMIN_PENDING, ADMIN_REPORT])
    return rows


def choose_city(chat_id: int, user_id: int) -> None:
    db.clear_state(user_id)
    db.set_state(user_id, "register_city")
    send_message(chat_id, "Выбери город:", [[city] for city in CITIES])


def save_city(chat_id: int, user: dict, city: str) -> None:
    name = " ".join(part for part in [user.get("first_name"), user.get("last_name")] if part) or "Без имени"
    db.upsert_manager(user["id"], name, city)
    db.clear_state(user["id"])
    send_message(chat_id, "Город сохранен.\n\nТеперь выбери действие кнопкой ниже.", main_menu(user["id"]))


def handle_start(chat_id: int, user: dict) -> None:
    db.clear_state(user["id"])
    manager = db.get_manager(user["id"])
    if not manager:
        choose_city(chat_id, user["id"])
        return
    send_message(chat_id, f"Ты привязан к городу: {manager.city}\n\nВыбери действие кнопкой ниже.", main_menu(user["id"]))


def start_add_review(chat_id: int, user_id: int) -> None:
    if not db.get_manager(user_id):
        choose_city(chat_id, user_id)
        return
    db.set_state(user_id, "review_office")
    send_message(chat_id, "Напиши точку/офис. Например: СЦ Авиамоторная")


def show_kpi(chat_id: int, user_id: int) -> None:
    rows = db.get_stats(user_id)
    if not rows:
        choose_city(chat_id, user_id)
        return
    row = rows[0]
    send_message(
        chat_id,
        f"KPI по менеджеру: {row['name']}\n"
        f"Город: {row['city']}\n"
        f"Всего отправлено: {row['total_reviews']}\n"
        f"На проверке: {row['pending_reviews']}\n"
        f"Подтверждено: {row['approved_reviews']}\n"
        f"Заработано: {row['earned']} руб.",
        main_menu(user_id),
    )


def handle_pending(chat_id: int, user_id: int) -> None:
    if user_id not in config.admin_ids:
        send_message(chat_id, "Команда доступна только администратору.", main_menu(user_id))
        return
    rows = db.list_pending_reviews()
    if not rows:
        send_message(chat_id, "Нет отзывов на проверке.", main_menu(user_id))
        return
    text = "\n\n".join(
        f"#{row['id']} | {row['name']} | {row['city']} | {row['platform']}\n"
        f"{row['review_text']}\n"
        f"/approve_{row['id']} или /reject_{row['id']}"
        for row in rows
    )
    send_message(chat_id, text, main_menu(user_id))


def handle_report(chat_id: int, user_id: int) -> None:
    if user_id not in config.admin_ids:
        send_message(chat_id, "Команда доступна только администратору.", main_menu(user_id))
        return
    rows = db.get_stats()
    if not rows:
        send_message(chat_id, "Пока нет менеджеров.", main_menu(user_id))
        return
    text = "Отчет по менеджерам:\n\n" + "\n".join(
        f"{row['name']} | {row['city']} | подтв.: {row['approved_reviews']} | "
        f"проверка: {row['pending_reviews']} | {row['earned']} руб."
        for row in rows
    )
    send_message(chat_id, text, main_menu(user_id))


def handle_review_state(chat_id: int, user_id: int, text: str, photo_id: str | None) -> None:
    state_row = db.get_state(user_id)
    if not state_row:
        send_message(chat_id, "Выбери действие кнопкой ниже.", main_menu(user_id))
        return

    state = state_row["state"]
    data = json.loads(state_row["data"])

    if state == "review_office":
        data["office"] = text
        db.set_state(user_id, "review_platform", json.dumps(data, ensure_ascii=False))
        send_message(chat_id, "Выбери платформу:", [[platform] for platform in PLATFORMS])
        return

    if state == "review_platform":
        data["platform"] = text
        db.set_state(user_id, "review_client", json.dumps(data, ensure_ascii=False))
        send_message(chat_id, "Имя клиента, ник или пометка. Если не знаешь, напиши '-'")
        return

    if state == "review_client":
        data["client_name"] = text
        db.set_state(user_id, "review_proof", json.dumps(data, ensure_ascii=False))
        send_message(chat_id, "Отправь фото/скрин отзыва или текст/ссылку.", remove_keyboard=True)
        return

    if state == "review_proof":
        proof_text = text or "Фото без подписи"
        review_id = db.add_review(
            manager_id=user_id,
            platform=data["platform"],
            client_name=data["client_name"],
            review_text=f"Точка: {data['office']}\nДоказательство: {proof_text}",
            attachment_file_id=photo_id,
            price=config.default_review_price,
        )
        db.clear_state(user_id)
        send_message(
            chat_id,
            f"Отзыв #{review_id} принят на проверку.\n"
            f"Сумма после подтверждения: {config.default_review_price} руб.",
            main_menu(user_id),
        )
        admin_text = (
            f"Новый отзыв #{review_id}\n"
            f"Менеджер ID: {user_id}\n"
            f"Точка: {data['office']}\n"
            f"Платформа: {data['platform']}\n"
            f"Клиент: {data['client_name']}\n"
            f"Доказательство: {proof_text}\n\n"
            f"Подтвердить: /approve_{review_id}\n"
            f"Отклонить: /reject_{review_id}"
        )
        for admin_id in config.admin_ids:
            if photo_id:
                send_photo(admin_id, photo_id, admin_text)
            else:
                send_message(admin_id, admin_text)


def handle_update(update: dict) -> None:
    message = update.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    user = message.get("from") or {}
    user_id = user.get("id")
    if not user_id:
        return

    text = (message.get("text") or message.get("caption") or "").strip()
    photo = message.get("photo") or []
    photo_id = photo[-1]["file_id"] if photo else None
    state_row = db.get_state(user_id)

    if text == "/start":
        handle_start(chat_id, user)
    elif text in (MENU_CITY, "/city"):
        choose_city(chat_id, user_id)
    elif text in (MENU_ADD, "/add"):
        start_add_review(chat_id, user_id)
    elif text in (MENU_KPI, "/kpi"):
        show_kpi(chat_id, user_id)
    elif text in (ADMIN_PENDING, "/pending"):
        handle_pending(chat_id, user_id)
    elif text in (ADMIN_REPORT, "/report"):
        handle_report(chat_id, user_id)
    elif text.startswith("/approve_") and user_id in config.admin_ids:
        review_id = int(text.rsplit("_", 1)[1])
        ok = db.set_review_status(review_id, "approved")
        send_message(chat_id, f"Отзыв #{review_id} подтвержден." if ok else f"Отзыв #{review_id} не найден.")
    elif text.startswith("/reject_") and user_id in config.admin_ids:
        review_id = int(text.rsplit("_", 1)[1])
        ok = db.set_review_status(review_id, "rejected")
        send_message(chat_id, f"Отзыв #{review_id} отклонен." if ok else f"Отзыв #{review_id} не найден.")
    elif text == MENU_HELP:
        send_message(chat_id, "Нажми «Отправить отзыв» и пройди шаги.\nKPI считается по подтвержденным отзывам.", main_menu(user_id))
    elif state_row and state_row["state"] == "register_city":
        save_city(chat_id, user, text)
    elif state_row:
        handle_review_state(chat_id, user_id, text, photo_id)
    elif db.get_manager(user_id):
        send_message(chat_id, "Выбери действие кнопкой ниже.", main_menu(user_id))
    else:
        choose_city(chat_id, user_id)


def main() -> None:
    db.init()
    offset = None
    print("Bot started", flush=True)
    while True:
        params = {"timeout": 25}
        if offset is not None:
            params["offset"] = offset
        try:
            result = api("getUpdates", params)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                handle_update(update)
        except Exception as exc:
            print(f"Polling error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
