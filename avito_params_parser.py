"""
avito_params_parser.py

Открывает страницу объявления Авито и собирает
параметры помещения из блока "О помещении".
Пример параметров:
  Вход: с улицы
  Общая площадь: 112.5 м²
  Этаж: 1
  Высота потолков: 3 м
  Отделка: офисная
  Отопление: центральное
  Тип аренды: прямая
"""

import requests
from bs4 import BeautifulSoup
from loguru import logger


# Заголовки чтобы Авито не блокировал запрос
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def get_avito_params(url_path: str, proxy: dict = None) -> dict:
    """
    Принимает urlPath объявления (например /moskva/... )
    Возвращает словарь с параметрами помещения.
    Если не удалось — возвращает пустой словарь {}.

    Пример результата:
    {
        "Вход": "с улицы",
        "Общая площадь": "112.5 м²",
        "Этаж": "1",
        "Высота потолков": "3 м",
        "Отделка": "офисная",
        "Отопление": "центральное",
        "Тип аренды": "прямая",
        "Арендные каникулы": "есть",
        "Минимальный срок аренды": "11 мес.",
        "Платежи включены": "эксплуатационные",
    }
    """
    if not url_path:
        return {}

    full_url = f"https://www.avito.ru{url_path}"

    try:
        response = requests.get(
            full_url,
            headers=HEADERS,
            proxies=proxy,
            timeout=15,
        )

        if response.status_code != 200:
            logger.warning(
                f"Страница {full_url} вернула {response.status_code}"
            )
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        params = {}

        # Способ 1: ищем параметры по data-marker (современная вёрстка Авито)
        # Авито хранит параметры в элементах с data-marker="item-params"
        # или в li внутри блока с параметрами
        params_block = soup.find(attrs={"data-marker": "item-params"})

        if params_block:
            # Ищем все строки параметров
            # Структура: <li><span>Название</span><span>Значение</span></li>
            items = params_block.find_all("li")
            for item in items:
                spans = item.find_all("span")
                if len(spans) >= 2:
                    key = spans[0].get_text(strip=True)
                    value = spans[1].get_text(strip=True)
                    # Убираем двоеточие в конце ключа если есть
                    key = key.rstrip(":")
                    if key and value:
                        params[key] = value

        # Способ 2: если первый не сработал — ищем по классу
        if not params:
            # Авито использует разные классы, пробуем несколько вариантов
            possible_selectors = [
                "ul[class*='params']",
                "ul[class*='item-params']",
                "div[class*='params'] li",
                "li[class*='param']",
            ]

            for selector in possible_selectors:
                found = soup.select(selector)
                if found:
                    for item in found:
                        spans = item.find_all("span")
                        if len(spans) >= 2:
                            key = spans[0].get_text(strip=True).rstrip(":")
                            value = spans[1].get_text(strip=True)
                            if key and value:
                                params[key] = value
                    if params:
                        break

        # Способ 3: ищем таблицу с параметрами
        if not params:
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    if len(cols) >= 2:
                        key = cols[0].get_text(strip=True).rstrip(":")
                        value = cols[1].get_text(strip=True)
                        if key and value:
                            params[key] = value

        if params:
            logger.info(
                f"Собрал {len(params)} параметров для {url_path}"
            )
        else:
            logger.warning(
                f"Параметры помещения не найдены для {url_path}"
            )

        return params

    except requests.exceptions.Timeout:
        logger.warning(f"Таймаут при загрузке {full_url}")
        return {}
    except requests.exceptions.ConnectionError:
        logger.warning(f"Ошибка соединения при загрузке {full_url}")
        return {}
    except Exception as err:
        logger.warning(f"Ошибка при парсинге параметров {full_url}: {err}")
        return {}