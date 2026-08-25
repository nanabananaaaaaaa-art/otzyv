import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: set[int]
    default_review_price: int
    database_path: str


def load_config() -> Config:
    load_dotenv_file()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Set BOT_TOKEN in environment or .env")

    admin_ids_raw = os.getenv("ADMIN_IDS", "")
    admin_ids = {
        int(item.strip())
        for item in admin_ids_raw.split(",")
        if item.strip().isdigit()
    }

    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        default_review_price=int(os.getenv("DEFAULT_REVIEW_PRICE", "100")),
        database_path=os.getenv("DATABASE_PATH", "bot.sqlite3"),
    )


def load_dotenv_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
