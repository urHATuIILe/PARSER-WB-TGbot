import aiohttp
import sys
import os
import asyncio
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    Message,
    CallbackQuery
)
from DataBaseWb.database import AsyncDatabaseManager
from tg_bot.config import BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, PROXY_URL


@dataclass
class ProductData:
    id: str
    name: str
    brand: str
    price: Optional[float]
    sale_price: Optional[float]
    wb_wallet: Optional[float]
    rating: str
    quantity: int
    supplier_name: str
    feedbacks: int
    entity: str
    link: str
    images: str

    @classmethod
    def from_dict(cls, data: dict) -> 'ProductData':
        return cls(
            id=str(data.get('id', '-')),
            name=data.get('name', 'Без названия'),
            brand=data.get('brand', '-'),
            price=data.get('price'),
            sale_price=data.get('sale_price'),
            wb_wallet=data.get('wb_wallet'),
            rating=data.get('rating', '-'),
            quantity=data.get('quantity', 0),
            supplier_name=data.get('supplier_name', '-'),
            feedbacks=data.get('feedbacks', 0),
            entity=data.get('entity', ''),
            link=data.get('link', '#'),
            images=data.get('images', '')
        )


@dataclass
class PhotoInfo:
    path: Path
    name: str
    size: int


class DatabaseService:

    def __init__(self):
        self._db_manager = AsyncDatabaseManager

    async def get_table_list(self) -> List[str]:
        async with self._db_manager() as db:
            return await db.list_tables()

    async def get_row_count(self, table_name: str) -> int:
        async with self._db_manager() as db:
            return await db.get_count(table_name)

    async def get_product(self, table_name: str, row_num: int) -> Optional[ProductData]:
        try:
            async with self._db_manager() as db:
                rows = await db.get_all(table_name, limit=10000)
                if row_num < 1 or row_num > len(rows):
                    return None
                return ProductData.from_dict(rows[row_num - 1])
        except Exception as e:
            logger.error(f"Ошибка получения данных: {e}")
            return None


class ImageService:

    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).parent.parent
        self.images_dir = self.base_dir / 'maker_images' / 'source_images'

    async def download_image(self, url: str, save_path: Path, timeout: int = 30) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                    if response.status == 200:
                        content = await response.read()
                        save_path.write_bytes(content)
                        return True
                    return False
        except Exception as e:
            logger.error(f"Ошибка скачивания {url}: {e}")
            return False

    async def download_images_batch(self, urls: List[str], table_name: str, row_num: int) -> Dict[str, int]:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        saved, failed = 0, 0
        for i, url in enumerate(urls):
            filename = f"{table_name}_{row_num}_{i + 1}.webp"
            filepath = self.images_dir / filename
            if await self.download_image(url, filepath):
                saved += 1
            else:
                failed += 1
            await asyncio.sleep(0.3)
        return {'saved': saved, 'failed': failed, 'total': len(urls)}

    def find_local_photos(self, table_name: str, row_num: int, item_id: str) -> List[PhotoInfo]:
        patterns = [f"{table_name}_{row_num}_*.webp", f"{item_id}_*.webp", "*.webp"]
        photos = []
        seen_names = set()
        for pattern in patterns:
            for filepath in self.images_dir.glob(pattern):
                if filepath.is_file() and filepath.stat().st_size > 0 and filepath.name not in seen_names:
                    seen_names.add(filepath.name)
                    photos.append(PhotoInfo(path=filepath, name=filepath.name, size=filepath.stat().st_size))
        return photos[:10]


class PostFormatter:

    @staticmethod
    def escape_html(text: str) -> str:
        if not text:
            return ''
        return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def format_post(self, product: ProductData) -> str:
        item_id = self.escape_html(product.id)
        name = self.escape_html(product.name[:100])
        brand = self.escape_html(product.brand)
        rating = self.escape_html(product.rating)
        supplier = self.escape_html(product.supplier_name)
        entity = self.escape_html(product.entity)
        link = product.link.replace('\u200B', '')

        parts = [f"🆔 <b>Артикул: {item_id}</b>"]
        prefix = '🔥' if product.sale_price else ''
        parts.append(f"\n{prefix} <b>{name}</b>")

        price_lines = self._format_prices(product)
        if price_lines:
            parts.append("\n" + "\n".join(price_lines))

        info = (f"\n🏷 Бренд: {brand}"
                f"\n⭐ Рейтинг: {rating} ({product.feedbacks} отзывов)"
                f"\n📦 В наличии: {product.quantity} шт"
                f"\n🏪 Продавец: {supplier}")
        if entity:
            info += f"\n📂 Категория: {entity}"
        parts.append(info)
        parts.append(f"\n\n🔗 <a href=\"{link}\">🛒 ПЕРЕЙТИ НА WILDBERRIES 🛒</a>")
        return "\n".join(parts)

    def _format_prices(self, product: ProductData) -> List[str]:
        lines = []
        if product.price:
            if product.sale_price and product.sale_price != product.price:
                discount = int(100 - (product.sale_price / product.price * 100))
                lines.append(f"💰 ~~{int(product.price):,}~~ → <b>{int(product.sale_price):,} ₽</b> (-{discount}%)")
                if product.wb_wallet:
                    lines.append(f"🛒 WB кошелёк: <b>{int(product.wb_wallet):,} ₽</b>")
            else:
                lines.append(f"💰 <b>{int(product.price):,} ₽</b>")
        return lines


class ParsingService:

    def __init__(self):
        self._lock = asyncio.Lock()

    async def is_parsing_running(self) -> bool:
        return self._lock.locked()

    async def start_parsing(self, query: str) -> Dict[str, Any]:
        if self._lock.locked():
            return {"success": False, "error": "Парсинг уже запущен"}
        async with self._lock:
            try:
                from main import parse
                logger.info(f"Запуск парсинга: {query}")
                result = await parse(search_phrase=query)
                return {"success": True, "result": result}
            except Exception as e:
                logger.error(f"Ошибка парсинга: {e}")
                return {"success": False, "error": str(e)}


class TgPostingBot:

    def __init__(self):
        self.bot = None
        self.dp = None
        self.db_service = DatabaseService()
        self.image_service = ImageService()
        self.formatter = PostFormatter()
        self.parsing_service = ParsingService()

    async def _create_bot(self):
        try:
            if PROXY_URL:
                session = AiohttpSession(proxy=PROXY_URL)
                self.bot = Bot(token=BOT_TOKEN, session=session)
                logger.info(f"Прокси: {PROXY_URL}")
            else:
                self.bot = Bot(token=BOT_TOKEN)

            info = await self.bot.get_me()
            logger.info(f"Бот: @{info.username}")

            self.dp = Dispatcher()
            self._register_handlers()
        except Exception as e:
            logger.error(f"Ошибка создания бота: {e}")
            raise

    def _register_handlers(self):
        self.dp.message(Command("start"))(self.cmd_start)
        self.dp.message(Command("post"))(self.cmd_post)
        self.dp.message(Command("preview"))(self.cmd_preview)
        self.dp.message(Command("tables"))(self.cmd_tables)
        self.dp.message(Command("parsing"))(self.cmd_parsing)
        self.dp.message(Command("images"))(self.cmd_images)

        @self.dp.callback_query(F.data.startswith('img_save_'))
        async def callback_img_save(callback: CallbackQuery):
            await self._on_save_one_photo(callback)

        @self.dp.callback_query(F.data.startswith('img_all_'))
        async def callback_img_all(callback: CallbackQuery):
            await self._on_save_all_photos(callback)

        @self.dp.callback_query(F.data == 'img_cancel')
        async def callback_img_cancel(callback: CallbackQuery):
            await callback.message.answer('Отменено')
            await callback.answer()

        @self.dp.callback_query(F.data.startswith('postphoto_'))
        async def callback_post_photo(callback: CallbackQuery):
            await self._on_post_with_photo(callback)

        @self.dp.callback_query(F.data == 'post_nophoto')
        async def callback_post_nophoto(callback: CallbackQuery):
            await self._on_post_without_photo(callback)

        @self.dp.callback_query(F.data == 'post_cancel')
        async def callback_post_cancel(callback: CallbackQuery):
            await callback.message.answer('❌ Отменено')
            await callback.answer()

    async def cmd_start(self, message: Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("<b>ДОСТУП ЗАПРЕЩЁН</b>", parse_mode=ParseMode.HTML)
            return
        text = ("⌨️ <b>Команды:</b>\n\n"
                "/parsing запрос — запустить парсер\n"
                "/post таблица номер — запостить\n"
                "/preview таблица номер — предпросмотр\n"
                "/images таблица номер — скачать фото\n"
                "/tables — список таблиц")
        await message.answer(text, parse_mode=ParseMode.HTML)

    async def cmd_tables(self, message: Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return
        try:
            tables = await self.db_service.get_table_list()
            if not tables:
                await message.answer("Таблиц нет")
                return
            text = f"<b>Таблицы ({len(tables)}):</b>\n\n"
            for i, table in enumerate(tables[:20], 1):
                count = await self.db_service.get_row_count(table)
                text += f"{i}. <code>{table}</code> ({count})\n"
            await message.answer(text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await message.answer(f"Ошибка: {e}")

    async def cmd_images(self, message: Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer("Формат:\n<code>/images таблица номер</code>", parse_mode=ParseMode.HTML)
            return
        table_name = args[1]
        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("Номер — число!")
            return
        product = await self.db_service.get_product(table_name, row_num)
        if not product:
            await message.answer(f"Не найдено: <code>{table_name}</code> строка {row_num}", parse_mode=ParseMode.HTML)
            return
        await message.answer(
            f"📷 <b>Изображения товара</b>\n\n"
            f"🆔 Артикул: <code>{product.id}</code>\n"
            f"📦 {product.name[:50]}",
            parse_mode=ParseMode.HTML
        )
        images_str = product.images
        if not images_str or images_str.strip() == '':
            await message.answer("<b>В БД нет изображений!</b>", parse_mode=ParseMode.HTML)
            return
        image_urls = [img.strip() for img in images_str.split(';') if img.strip()]
        if not image_urls:
            await message.answer("<b>Ссылки пустые!</b>", parse_mode=ParseMode.HTML)
            return
        total_count = len(image_urls)
        preview_count = min(5, total_count)
        for i in range(preview_count):
            try:
                caption = f"{i + 1}/{total_count}"
                await self.bot.send_photo(chat_id=message.chat.id, photo=image_urls[i], caption=caption)
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"Превью {i + 1} не загрузилось: {e}")
        buttons = []
        row = []
        max_buttons = min(total_count, 10)
        for i in range(max_buttons):
            row.append(InlineKeyboardButton(text=f"📷 {i + 1}", callback_data=f"img_save_{table_name}_{row_num}_{product.id}_{i}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(text="Все фото", callback_data=f"img_all_{table_name}_{row_num}_{product.id}"),
            InlineKeyboardButton(text="Отмена", callback_data="img_cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            f"<b>Выбери фото:</b>\n\n"
            f"Всего: <b>{total_count}</b> шт\n"
            f"Имя файла: <code>{table_name}_{row_num}_номер.webp</code>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    async def _on_save_one_photo(self, callback: CallbackQuery):
        data_str = callback.data.replace('img_save_', '')
        all_parts = data_str.split('_')
        if len(all_parts) < 4:
            await callback.answer("Ошибка данных", show_alert=True)
            return
        try:
            img_index = int(all_parts[-1])
            item_id = int(all_parts[-2])
            row_num = int(all_parts[-3])
            table_name = '_'.join(all_parts[:-3])
        except (ValueError, IndexError):
            await callback.answer("Ошибка формата", show_alert=True)
            return
        product = await self.db_service.get_product(table_name, row_num)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        image_urls = [img.strip() for img in product.images.split(';') if img.strip()]
        if not image_urls or img_index >= len(image_urls):
            await callback.answer("Фото не найдено", show_alert=True)
            return
        url = image_urls[img_index]
        total = len(image_urls)
        filename = f"{table_name}_{row_num}_{img_index + 1}.webp"
        filepath = self.image_service.images_dir / filename
        await callback.message.answer(f"Скачиваю фото {img_index + 1}...")
        try:
            success = await self.image_service.download_image(url, filepath)
            if success:
                with open(filepath, 'rb') as file:
                    file_data = file.read()
                photo_buffer = BufferedInputFile(file_data, filename=os.path.basename(filepath))
                await callback.message.answer_photo(
                    photo=photo_buffer,
                    caption=(
                        f"<b>Сохранено!</b>\n\n"
                        f"<code>{filename}</code>\n"
                        f"Фото: {img_index + 1} / {total}\n"
                        f"Таблица: <code>{table_name}</code>"
                    ),
                    parse_mode=ParseMode.HTML
                )
            else:
                await callback.message.answer(f"Ошибка HTTP при скачивании")
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            await callback.message.answer(f"Ошибка: {e}")
        await callback.answer("Готово!")

    async def _on_save_all_photos(self, callback: CallbackQuery):
        data_str = callback.data.replace('img_all_', '')
        all_parts = data_str.split('_')
        if len(all_parts) < 3:
            await callback.answer("Ошибка данных", show_alert=True)
            return
        try:
            item_id = int(all_parts[-1])
            row_num = int(all_parts[-2])
            table_name = '_'.join(all_parts[:-2])
        except (ValueError, IndexError):
            await callback.answer("Ошибка формата", show_alert=True)
            return
        product = await self.db_service.get_product(table_name, row_num)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        image_urls = [img.strip() for img in product.images.split(';') if img.strip()]
        total = len(image_urls)
        await callback.message.answer(f"Скачиваю все {total} фото...")
        result = await self.image_service.download_images_batch(image_urls, table_name, row_num)
        await callback.message.answer(
            f"<b>Готово!</b>\n\n"
            f"<code>{table_name}</code>\n"
            f"Папка: <code>maker_images/source_images/</code>\n"
            f"Сохранено: <b>{result['saved']}</b> / {total}\n"
            f"Ошибок: <b>{result['failed']}</b>",
            parse_mode=ParseMode.HTML
        )
        await callback.answer(f"Сохранено {result['saved']} фото!")

    async def cmd_post(self, message: Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer("Формат:\n<code>/post таблица номер</code>", parse_mode=ParseMode.HTML)
            return
        table_name = args[1]
        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("Номер — число!")
            return
        product = await self.db_service.get_product(table_name, row_num)
        if not product:
            await message.answer(f"Не найдено: <code>{table_name}</code> строка {row_num}", parse_mode=ParseMode.HTML)
            return
        post_text = self.formatter.format_post(product)
        available_photos = self.image_service.find_local_photos(table_name, row_num, product.id)
        if not available_photos:
            try:
                msg = await self.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text="+",
                    url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                )]])
                await message.answer(
                    f"Опубликовано! 📝\n\n"
                    f"<code>{table_name}</code>\n"
                    f"Строка: {row_num}\n\n"
                    f"Фото не найдено!\n"
                    f"Сначала: <code>/images {table_name} {row_num}</code>",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                await message.answer(f"Ошибка: {e}")
            return
        await message.answer(
            f"<b>Выбери фото для поста:</b>\n\n"
            f"Артикул: <code>{product.id}</code>\n"
            f"{product.name[:50]}\n\n"
            f"Доступно: <b>{len(available_photos)}</b> шт",
            parse_mode=ParseMode.HTML
        )
        for i, photo in enumerate(available_photos[:3]):
            try:
                with open(photo.path, 'rb') as file:
                    file_data = file.read()
                photo_buf = BufferedInputFile(file_data, filename=photo.name)
                await self.bot.send_photo(
                    chat_id=message.chat.id,
                    photo=photo_buf,
                    caption=f"{i + 1}/{len(available_photos)}"
                )
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"Превью не загрузилось: {e}")
        buttons = []
        row = []
        for i, photo in enumerate(available_photos):
            row.append(InlineKeyboardButton(
                text=f"{i + 1}",
                callback_data=f"postphoto_{table_name}_{row_num}_{product.id}_{i}"
            ))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(text="Без фото", callback_data="post_nophoto"),
            InlineKeyboardButton(text="Отмена", callback_data="post_cancel")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            f"<b>Выбери фото:</b>\n\n"
            f"Таблица: <code>{table_name}</code>\n"
            f"Строка: {row_num}",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    async def _on_post_with_photo(self, callback: CallbackQuery):
        data_str = callback.data.replace('postphoto_', '')
        all_parts = data_str.split('_')
        if len(all_parts) < 4:
            await callback.answer("Ошибка", show_alert=True)
            return
        try:
            img_index = int(all_parts[-1])
            item_id = int(all_parts[-2])
            row_num = int(all_parts[-3])
            table_name = '_'.join(all_parts[:-3])
        except (ValueError, IndexError):
            await callback.answer("Ошибка формата", show_alert=True)
            return
        product = await self.db_service.get_product(table_name, row_num)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        post_text = self.formatter.format_post(product)
        photos = self.image_service.find_local_photos(table_name, row_num, item_id)
        if img_index >= len(photos):
            await callback.answer("Фото не найдено", show_alert=True)
            return
        photo_path = photos[img_index].path
        filename = os.path.basename(photo_path)
        try:
            with open(photo_path, 'rb') as file:
                file_data = file.read()
            photo_buffer = BufferedInputFile(file_data, filename=filename)
            msg = await self.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo_buffer,
                caption=post_text,
                parse_mode=ParseMode.HTML
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="+",
                    url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                ),
                 InlineKeyboardButton(text="🗑️", callback_data=f"del_{msg.message_id}")]
            ])
            await callback.message.answer(
                f"Опубликовано! 📷\n\n"
                f"<code>{filename}</code>\n"
                f"<code>{table_name}</code>\n"
                f"Строка: {row_num}",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            await callback.answer("Готово!")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await callback.message.answer(f"Ошибка: {e}")

    async def _on_post_without_photo(self, callback: CallbackQuery):
        data_str = callback.data.replace('post_nophoto_', '')
        parts = data_str.split('_')
        if len(parts) < 2:
            table_name = data_str
            row_num = 1
        else:
            row_num = int(parts[-1])
            table_name = '_'.join(parts[:-1])
        product = await self.db_service.get_product(table_name, row_num)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        post_text = self.formatter.format_post(product)
        try:
            msg = await self.bot.send_message(
                chat_id=CHANNEL_ID,
                text=post_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                text="+",
                url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
            )]])
            await callback.message.answer(
                f"Опубликовано! 📝\n\n"
                f"<code>{table_name}</code>\n"
                f"Строка: {row_num}",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            await callback.answer("Готово!")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await callback.message.answer(f"Ошибка: {e}")

    async def cmd_preview(self, message: Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer("Формат:\n<code>/preview таблица номер</code>", parse_mode=ParseMode.HTML)
            return
        table_name = args[1]
        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("Номер — число!")
            return
        product = await self.db_service.get_product(table_name, row_num)
        if not product:
            await message.answer("Не найдено")
            return
        post_text = self.formatter.format_post(product)
        await message.answer(f"<b>PREVIEW</b>\n\n{post_text}", parse_mode=ParseMode.HTML)

    async def cmd_parsing(self, message: Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return
        if await self.parsing_service.is_parsing_running():
            await message.answer("⏳ Парсинг уже запущен! Дождись окончания.")
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Формат:\n<code>/parsing запрос</code>", parse_mode=ParseMode.HTML)
            return
        query = args[1].strip()
        status_msg = await message.answer(
            f"<b>Запускаю парсинг...</b>\n\n"
            f"Запрос: <code>{query}</code>\n\n"
            f"Ожидайте...",
            parse_mode=ParseMode.HTML
        )
        result = await self.parsing_service.start_parsing(query)
        if result.get("success"):
            result_data = result["result"]
            if result_data and len(result_data) > 0:
                table_name = query.lower().replace(' ', '_').replace('-', '_')
                db_count = await self.db_service.get_row_count(table_name)
                await status_msg.edit_text(
                    f"<b>ПАРСИНГ ЗАВЕРШЁН!</b>\n\n"
                    f"Запрос: <code>{query}</code>\n"
                    f"Таблица: <code>{table_name}</code>\n"
                    f"Товаров: <b>{db_count}</b> шт\n\n"
                    f"Постить:\n<code>/post {table_name} 1</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await status_msg.edit_text(
                    f"<b>ПАРСИНГ ЗАВЕРШЁН!</b>\n\n"
                    f"Запрос: <code>{query}</code>\n"
                    f"Товаров: <b>0</b>",
                    parse_mode=ParseMode.HTML
                )
        else:
            error = result.get("error", "Неизвестная ошибка")
            await status_msg.edit_text(f"<b>ОШИБКА ПАРСИНГА</b>\n\n{error[:500]}", parse_mode=ParseMode.HTML)

    async def run(self):
        await self._create_bot()
        logger.info("Бот запущен")
        await self.bot.delete_webhook(drop_pending_updates=True)
        await self.dp.start_polling(self.bot)


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    bot = TgPostingBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")