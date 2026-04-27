import os
import tomllib
from pathlib import Path
import tomli_w
from dto import AvitoConfig


def load_avito_config(path: str = "config.toml") -> AvitoConfig:
    """
    Загружает конфиг из config.toml
    Затем подставляет секретные данные
    из переменных окружения Railway
    Переменные окружения имеют приоритет
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    avito_data = data["avito"]

    # Токен бота
    # Берём из переменной окружения если есть
    tg_token = os.environ.get("TG_TOKEN", "")
    if tg_token:
        avito_data["tg_token"] = tg_token

    # Chat ID
    tg_chat_id = os.environ.get("TG_CHAT_ID", "")
    if tg_chat_id:
        avito_data["tg_chat_id"] = [tg_chat_id]

    # Ключ cookies API
    cookies_key = os.environ.get("COOKIES_API_KEY", "")
    if cookies_key:
        avito_data["cookies_api_key"] = cookies_key

    return AvitoConfig(**avito_data)


def save_avito_config(config: dict):
    with Path("config.toml").open("wb") as f:
        tomli_w.dump(config, f)