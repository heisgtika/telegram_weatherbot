"""Telegram-бот для получения погоды по названию города."""

import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)


LOGGER = logging.getLogger(__name__)
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
HELP_TEXT = (
    "Я умею показывать погоду.\n\n"
    "Напишите сообщение со словом «погода» и названием города, например:\n"
    "«Погода в Алматы»\n"
    "«Какая погода сейчас в Астане?»"
)


@dataclass(frozen=True)
class Weather:
    """Данные о погоде, которые нужны для ответа пользователю."""

    city: str
    temperature: float
    feels_like: float
    description: str


def get_required_env(name: str) -> str:
    """Возвращает обязательную переменную окружения или сообщает об ошибке."""

    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return value


def extract_city(text: str) -> str | None:
    """Достаёт название города из типичных русских фраз о погоде."""

    normalized = " ".join(text.split()).strip()
    match = re.search(
        r"\b(?:в|во|для|города?)\s+([А-Яа-яЁёA-Za-zÀ-ÖØ-öø-ÿ][А-Яа-яЁёA-Za-zÀ-ÖØ-öø-ÿ\s-]*?)(?:\s*[?!,.;:]|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if match:
        city = match.group(1).strip(" -")
        if city and city.lower() not in {"сейчас", "городе", "город"}:
            return city

    # Поддерживаем короткий вариант: «погода Алматы».
    weather_match = re.search(
        r"\bпогода\s+([А-Яа-яЁёA-Za-zÀ-ÖØ-öø-ÿ][А-Яа-яЁёA-Za-zÀ-ÖØ-öø-ÿ\s-]*?)(?:\s*[?!,.;:]|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if weather_match:
        return weather_match.group(1).strip(" -") or None
    return None


def fetch_weather(city: str, api_key: str) -> Weather:
    """Запрашивает текущую погоду в OpenWeatherMap."""

    query = urlencode(
        {
            "q": city,
            "appid": api_key,
            "units": "metric",
            "lang": "ru",
        }
    )
    request = Request(f"{WEATHER_URL}?{query}", headers={"User-Agent": "replit-weather-bot/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError("город не найден") from error
        LOGGER.exception("OpenWeatherMap вернул HTTP %s", error.code)
        raise RuntimeError("сервис погоды временно недоступен") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        LOGGER.exception("Не удалось получить погоду")
        raise RuntimeError("не удалось связаться с сервисом погоды") from error

    try:
        return Weather(
            city=str(data["name"]),
            temperature=float(data["main"]["temp"]),
            feels_like=float(data["main"]["feels_like"]),
            description=str(data["weather"][0]["description"]).capitalize(),
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        LOGGER.exception("OpenWeatherMap вернул неожиданный ответ")
        raise RuntimeError("сервис погоды вернул некорректный ответ") from error


def format_temperature(value: float) -> str:
    """Форматирует температуру без лишнего десятичного нуля."""

    return f"{value:.1f}".replace(".0", "")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает обычные текстовые сообщения."""

    if not update.message or not update.message.text:
        return

    text = update.message.text
    if "погода" not in text.lower():
        await update.message.reply_text(HELP_TEXT)
        return

    city = extract_city(text)
    if not city:
        await update.message.reply_text(
            "Не удалось понять, для какого города нужна погода. "
            "Напишите, например: «Погода в Алматы»."
        )
        return

    api_key = context.application.bot_data["weather_key"]
    try:
        weather = fetch_weather(city, api_key)
    except ValueError:
        await update.message.reply_text(
            f"Не удалось найти город «{city}». Проверьте название и попробуйте ещё раз."
        )
        return
    except RuntimeError:
        await update.message.reply_text(
            "К сожалению, сейчас не получается получить данные о погоде. "
            "Попробуйте немного позже."
        )
        return

    await update.message.reply_text(
        f"Погода в городе {weather.city}\n"
        f"Температура: {format_temperature(weather.temperature)} °C\n"
        f"Ощущается как: {format_temperature(weather.feels_like)} °C\n"
        f"Описание: {weather.description}"
    )


def main() -> None:
    """Создаёт приложение и запускает long polling."""

    logging.basicConfig(
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        level=logging.INFO,
    )
    bot_token = get_required_env("BOT_TOKEN")
    weather_key = get_required_env("WEATHER_KEY")

    application = Application.builder().token(bot_token).build()
    application.bot_data["weather_key"] = weather_key
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    LOGGER.info("Бот запущен и ожидает сообщения")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()