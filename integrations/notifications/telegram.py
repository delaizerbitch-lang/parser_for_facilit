import requests
from loguru import logger
from datetime import datetime, timezone

from integrations.notifications.base import Notifier
from integrations.notifications.transport import send_with_retries
from models import Item


class TelegramNotifier(Notifier):
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        proxy: str = None,
        only_text: bool = False
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.proxy = self._get_proxy(proxy=proxy)
        self.only_text = only_text

    @staticmethod
    def _get_proxy(proxy: str = None) -> dict | None:
        if proxy:
            return {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}",
            }
        return None

    def _api(self, method: str) -> str:
        return (
            f"https://api.telegram.org/"
            f"bot{self.bot_token}/{method}"
        )

    @staticmethod
    def _collect_photos(ad: Item) -> list[str]:
        photos = []

        if ad.gallery and ad.gallery.image_large_urls:
            for url in ad.gallery.image_large_urls:
                url_str = str(url) if url else None
                if url_str and url_str not in photos:
                    photos.append(url_str)

        if not photos and ad.images:
            for image_obj in ad.images:
                if image_obj and image_obj.root:
                    best_url = None
                    best_size = 0
                    for size_key, url in image_obj.root.items():
                        try:
                            parts = size_key.split("x")
                            if len(parts) == 2:
                                size = int(parts[0]) * int(parts[1])
                                if size > best_size:
                                    best_size = size
                                    best_url = str(url)
                        except (ValueError, AttributeError):
                            best_url = str(url)
                    if best_url and best_url not in photos:
                        photos.append(best_url)

        if not photos:
            if ad.gallery and ad.gallery.imageLargeUrl:
                photos.append(str(ad.gallery.imageLargeUrl))

        return photos[:20]

    @staticmethod
    def _get_age_string(ad: Item) -> str:
        """
        Считает возраст объявления через sortTimeStamp.
        sortTimeStamp — это миллисекунды (13 цифр).
        """
        try:
            if not ad.sortTimeStamp:
                return ""

            ts = ad.sortTimeStamp

            # Авито хранит время в миллисекундах — делим на 1000
            if ts > 1_000_000_000_000:
                ts = ts / 1000

            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            delta = now - dt
            days = delta.days

            if days == 0:
                hours = delta.seconds // 3600
                if hours == 0:
                    minutes = delta.seconds // 60
                    return f"🕐 Опубликовано: {minutes} мин. назад"
                return f"🕐 Опубликовано: {hours} ч. назад"
            elif days == 1:
                return "🕐 Опубликовано: вчера"
            elif days < 7:
                return f"🕐 Опубликовано: {days} дн. назад"
            elif days < 30:
                weeks = days // 7
                return f"🕐 Опубликовано: {weeks} нед. назад"
            else:
                months = days // 30
                return f"🕐 Опубликовано: {months} мес. назад"

        except Exception:
            return ""

    def format(self, ad: Item) -> str:
        """
        Формирует сообщение для Telegram.
        Показывает: название, цена, адрес, возраст,
        параметры помещения, продавец, ссылка.
        Описание НЕ показываем.
        """
        lines = []

        # Заголовок
        title = ad.title or "Без названия"
        lines.append(f"📌 {title}")
        lines.append("")

        # Цена
        if ad.priceDetailed:
            price = (
                ad.priceDetailed.string
                or str(ad.priceDetailed.value)
            )
            lines.append(f"💰 Цена: {price}")

        # Адрес
        address = ""
        if ad.geo and ad.geo.formattedAddress:
            address = ad.geo.formattedAddress
        elif (
            ad.addressDetailed
            and ad.addressDetailed.locationName
        ):
            address = ad.addressDetailed.locationName

        if address:
            lines.append(f"📍 Адрес: {address}")

        # Возраст объявления
        age_str = self._get_age_string(ad)
        if age_str:
            lines.append(age_str)

        # Параметры помещения
        # Они кладутся в ad.params парсером avito_params_parser.py
        if hasattr(ad, 'params') and ad.params:
            lines.append("")
            lines.append("🏢 О помещении:")
            if isinstance(ad.params, dict):
                for key, value in ad.params.items():
                    lines.append(f"  • {key}: {value}")
            elif isinstance(ad.params, list):
                for param in ad.params:
                    if isinstance(param, dict):
                        key = param.get('title') or param.get('name') or ''
                        value = param.get('value') or ''
                        if isinstance(value, dict):
                            value = value.get('title') or str(value)
                        if key:
                            lines.append(f"  • {key}: {value}")
                    else:
                        lines.append(f"  • {param}")

        # Продавец
        if ad.sellerId:
            lines.append("")
            lines.append(f"👤 Продавец: {ad.sellerId}")

        # Количество фото
        if ad.imagesCount:
            lines.append(f"📸 Фото: {ad.imagesCount} шт.")

        # Ссылка
        if ad.urlPath:
            url = f"https://www.avito.ru{ad.urlPath}"
            lines.append("")
            lines.append(f"🔗 {url}")

        return "\n".join(lines)

    def _send_text(self, text: str) -> None:
        """Отправляет текст без форматирования"""
        def _send():
            return requests.post(
                self._api("sendMessage"),
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                proxies=self.proxy,
                timeout=10,
            )
        send_with_retries(_send)

    def _send_single_photo(
        self,
        photo_url: str,
        caption: str
    ) -> None:
        """Отправляет одно фото с подписью"""
        def _send():
            return requests.post(
                self._api("sendPhoto"),
                json={
                    "chat_id": self.chat_id,
                    "photo": photo_url,
                    "caption": caption[:1024],
                },
                proxies=self.proxy,
                timeout=15,
            )
        send_with_retries(_send)

    def _send_media_group(
        self,
        photos: list[str],
        caption: str = ""
    ) -> None:
        """Отправляет альбом до 10 фото"""
        if not photos:
            return

        media = []
        for i, photo_url in enumerate(photos):
            item = {
                "type": "photo",
                "media": photo_url
            }
            if i == 0 and caption:
                item["caption"] = caption[:1024]
            media.append(item)

        def _send():
            return requests.post(
                self._api("sendMediaGroup"),
                json={
                    "chat_id": self.chat_id,
                    "media": media,
                },
                proxies=self.proxy,
                timeout=30,
            )
        send_with_retries(_send)

    def _send_all_photos(
        self,
        photos: list[str],
        caption: str
    ) -> None:
        """Все фото альбомами по 10"""
        if not photos:
            self._send_text(caption)
            return

        if len(photos) == 1:
            self._send_single_photo(
                photo_url=photos[0],
                caption=caption
            )
            return

        chunks = [
            photos[i:i + 10]
            for i in range(0, len(photos), 10)
        ]

        for index, chunk in enumerate(chunks):
            album_caption = caption if index == 0 else ""

            if len(chunk) == 1:
                self._send_single_photo(
                    photo_url=chunk[0],
                    caption=album_caption
                )
            else:
                self._send_media_group(
                    photos=chunk,
                    caption=album_caption
                )

    def notify_ad(self, ad: Item) -> None:
        try:
            message = self.format(ad)

            if self.only_text:
                self._send_text(message)
                return

            photos = self._collect_photos(ad)

            logger.info(
                f"Отправляю {ad.id} | "
                f"фото: {len(photos)} | "
                f"{ad.title}"
            )

            self._send_all_photos(
                photos=photos,
                caption=message
            )

        except Exception as err:
            logger.error(
                f"Ошибка отправки {ad.id}: {err}"
            )

    def notify_message(self, message: str) -> None:
        self._send_text(message)

    def notify(
        self,
        ad: Item = None,
        message: str = None
    ) -> None:
        if ad:
            return self.notify_ad(ad=ad)
        if message:
            return self.notify_message(message=message)