import requests
from loguru import logger
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
        """
        Собирает все ссылки на фото из объявления
        Пробует три источника по приоритету
        """
        photos = []

        # Источник 1 — большие фото из галереи
        if ad.gallery and ad.gallery.image_large_urls:
            for url in ad.gallery.image_large_urls:
                url_str = str(url) if url else None
                if url_str and url_str not in photos:
                    photos.append(url_str)

        # Источник 2 — список images
        if not photos and ad.images:
            for image_obj in ad.images:
                if image_obj and image_obj.root:
                    best_url = None
                    best_size = 0
                    for size_key, url in image_obj.root.items():
                        try:
                            parts = size_key.split("x")
                            if len(parts) == 2:
                                size = (
                                    int(parts[0]) * int(parts[1])
                                )
                                if size > best_size:
                                    best_size = size
                                    best_url = str(url)
                        except (ValueError, AttributeError):
                            best_url = str(url)
                    if best_url and best_url not in photos:
                        photos.append(best_url)

        # Источник 3 — одно большое фото
        if not photos:
            if ad.gallery and ad.gallery.imageLargeUrl:
                photos.append(str(ad.gallery.imageLargeUrl))

        return photos[:20]

    @staticmethod
    def _escape(text: str) -> str:
        """
        Экранирует спецсимволы для MarkdownV2
        Без этого Telegram выдаёт ошибку
        """
        if not text:
            return ""
        special = r"\_*[]()~`>#+-=|{}.!"
        for ch in special:
            text = text.replace(ch, f"\\{ch}")
        return text

    def format(self, ad: Item) -> str:
        """
        Формирует текст сообщения
        Содержит все данные объявления
        """

        # Заголовок
        title = self._escape(ad.title or "Без названия")

        # Цена
        price = ""
        if ad.priceDetailed:
            price = self._escape(
                ad.priceDetailed.string
                or str(ad.priceDetailed.value)
            )

        # Адрес
        address = ""
        if ad.geo and ad.geo.formattedAddress:
            address = self._escape(ad.geo.formattedAddress)
        elif (
            ad.addressDetailed
            and ad.addressDetailed.locationName
        ):
            address = self._escape(
                ad.addressDetailed.locationName
            )

        # Описание до 800 символов
        description = ""
        if ad.description:
            desc_raw = ad.description[:800]
            if len(ad.description) > 800:
                desc_raw += "..."
            description = self._escape(desc_raw)

        # Продавец
        seller = self._escape(ad.sellerId or "Не указан")

        # Ссылка
        url = ""
        if ad.urlPath:
            url = f"https://www.avito.ru{ad.urlPath}"

        # Количество фото
        photos_count = ad.imagesCount or 0

        # Собираем сообщение по блокам
        lines = []

        lines.append(f"*{title}*")
        lines.append("")

        if price:
            lines.append(f"💰 *{price}*")
        if address:
            lines.append(f"📍 {address}")
        if seller:
            lines.append(f"👤 Продавец: {seller}")
        if photos_count:
            lines.append(f"📸 Фото: {photos_count} шт\\.")

        if description:
            lines.append("")
            lines.append("📝 *Описание:*")
            lines.append(description)

        if url:
            lines.append("")
            lines.append(f"🔗 [Открыть объявление]({url})")

        return "\n".join(lines)

    def _send_text(self, text: str) -> None:
        """Отправляет текстовое сообщение"""
        def _send():
            return requests.post(
                self._api("sendMessage"),
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
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
                    "parse_mode": "MarkdownV2",
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
                item["parse_mode"] = "MarkdownV2"
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
        """
        Отправляет все фото альбомами по 10
        Первый альбом с подписью текста
        """
        if not photos:
            self._send_text(caption)
            return

        if len(photos) == 1:
            self._send_single_photo(
                photo_url=photos[0],
                caption=caption
            )
            return

        # Разбиваем на группы по 10
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
        """Главный метод — отправляет объявление"""
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