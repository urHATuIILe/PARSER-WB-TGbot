"""
Telegram Bot для posting + parsing + images
"""

import sys
import os
import asyncio
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from pars.DataBaseWb.database import DatabaseManager
from pars.tg_bot.config import BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, PROXY_URL


class TgPostingBot:

    def __init__(self):
        self.bot = None
        self.dp = None
        self._parsing_lock = threading.Lock()

    async def _create_bot(self):
        from aiogram import Bot, Dispatcher
        from aiogram.client.session.aiohttp import AiohttpSession

        if PROXY_URL:
            session = AiohttpSession(proxy=PROXY_URL)
            self.bot = Bot(token=BOT_TOKEN, session=session)
            logger.info(f"Прокси: {PROXY_URL}")
        else:
            self.bot = Bot(token=BOT_TOKEN)

        self.dp = Dispatcher()
        self._register_handlers()

    def _register_handlers(self):
        from aiogram.filters import Command

        self.dp.message(Command("start"))(self.cmd_start)
        self.dp.message(Command("post"))(self.cmd_post)
        self.dp.message(Command("preview"))(self.cmd_preview)
        self.dp.message(Command("tables"))(self.cmd_tables)
        self.dp.message(Command("parsing"))(self.cmd_parsing)
        self.dp.message(Command("images"))(self.cmd_images)

        # Callback для выбора фото
        from aiogram import F, types as types_msg

        @self.dp.callback_query(F.data.startswith('img_save_'))
        async def callback_img_save(callback):
            await self._on_save_one_photo(callback)

        @self.dp.callback_query(F.data.startswith('img_all_'))
        async def callback_img_all(callback):
            await self._on_save_all_photos(callback)

        @self.dp.callback_query(F.data == 'img_cancel')
        async def callback_img_cancel(callback):
            await callback.message.answer('❌ Отменено')
            await callback.answer()

    # ============================================
    # КОМАНДЫ
    # ============================================

    async def cmd_start(self, message):
        from aiogram.enums import ParseMode

        if message.from_user.id not in ADMIN_IDS:
            await message.answer(
                "❌ <b>ДОСТУП ЗАПРЕЩЁН</b>",
                parse_mode=ParseMode.HTML
            )
            return

        await message.answer(
            "⌨️ <b>Команды:</b>\n\n"
            "/parsing запрос — запустить парсер\n"
            "/post таблица номер — запостить\n"
            "/preview таблица номер — предпросмотр\n"
            "/images таблица номер — скачать фото\n"
            "/tables — список таблиц",
            parse_mode=ParseMode.HTML
        )

    async def cmd_tables(self, message):
        from aiogram.enums import ParseMode

        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Нет доступа")
            return

        try:
            with DatabaseManager() as db:
                tables = db.list_tables()

            if not tables:
                await message.answer("📭 Таблиц нет")
                return

            text = f"📊 <b>Таблицы ({len(tables)}):</b>\n\n"

            for i, table in enumerate(tables[:20], 1):
                with DatabaseManager() as db_count:
                    count = db_count.get_count(table)
                text += f"{i}. <code>{table}</code> ({count})\n"

            await message.answer(text, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await message.answer(f"❌ Ошибка: {e}")

    async def cmd_images(self, message):
        from aiogram.enums import ParseMode
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        import asyncio

        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Нет доступа")
            return

        args = message.text.split(maxsplit=2)

        if len(args) < 3:
            await message.answer(
                "❌ Формат:\n<code>/images таблица номер</code>",
                parse_mode=ParseMode.HTML
            )
            return

        table_name = args[1]

        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("❌ Номер — число!")
            return

        # Получаем данные из БД
        data = self._get_row(table_name, row_num)

        if not data:
            await message.answer(
                f"❌ Не найдено: <code>{table_name}</code> строка {row_num}",
                parse_mode=ParseMode.HTML
            )
            return

        item_id = data.get('id', '-')
        name = data.get('name', 'Без названия')[:50]
        images_str = data.get('images', '')

        # Инфо о товаре
        await message.answer(
            f"📷 <b>Изображения товара</b>\n\n"
            f"🆔 Артикул: <code>{item_id}</code>\n"
            f"📦 {name}",
            parse_mode=ParseMode.HTML
        )

        # Проверяем есть ли изображения
        if not images_str or images_str.strip() == '':
            await message.answer("⚠️ <b>В БД нет изображений!</b>", parse_mode=ParseMode.HTML)
            return

        # Разделяем изображения
        image_urls = [img.strip() for img in images_str.split(';') if img.strip()]

        if not image_urls:
            await message.answer("⚠️ <b>Ссылки пустые!</b>", parse_mode=ParseMode.HTML)
            return

        total_count = len(image_urls)

        # Показываем превью (первые 5)
        preview_count = min(5, total_count)

        for i in range(preview_count):
            try:
                caption = f"📷 {i + 1}/{total_count}" if i == 0 else f"{i + 1}/{total_count}"

                await self.bot.send_photo(
                    chat_id=message.chat.id,
                    photo=image_urls[i],
                    caption=caption
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"Превью {i + 1} не загрузилось: {e}")

        # Кнопки выбора
        buttons = []
        row = []

        max_buttons = min(total_count, 10)

        for i in range(max_buttons):
            row.append(
                InlineKeyboardButton(
                    text=f"📷 {i + 1}",
                    callback_data=f"img_save_{table_name}_{row_num}_{item_id}_{i}"
                )
            )

            if len(row) == 5:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

        # Доп кнопки
        buttons.append([
            InlineKeyboardButton(text="💾 Все фото",
                                 callback_data=f"img_all_{table_name}_{row_num}_{item_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="img_cancel")
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            f"👇 <b>Выбери фото для скачивания:</b>\n\n"
            f"📊 Всего: <b>{total_count}</b> шт\n"
            f"📁 Имя файла: <code>{table_name}_{row_num}_номер.webp</code>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    async def _on_save_one_photo(self, callback):
        """Сохранение одного выбранного фото"""
        from aiogram.enums import ParseMode
        from aiogram.types import FSInputFile  # ← ДОБАВИТЬ ЭТОТ ИМПОРТ!
        import os
        import aiohttp

        parts = callback.data.replace('img_save_', '').split('_')

        table_name = parts[0]
        row_num = int(parts[1])
        item_id = int(parts[2])
        img_index = int(parts[3])

        # Получаем данные из БД
        data = self._get_row(table_name, row_num)

        if not data:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return

        images_str = data.get('images', '')
        image_urls = [img.strip() for img in images_str.split(';') if img.strip()]

        if img_index >= len(image_urls):
            await callback.answer("❌ Фото не найдено", show_alert=True)
            return

        url = image_urls[img_index]
        total = len(image_urls)

        # Папка для сохранения
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'maker_images', 'source_images')
        os.makedirs(save_dir, exist_ok=True)

        filename = f"{table_name}_{row_num}_{img_index + 1}.webp"
        filepath = os.path.join(save_dir, filename)

        await callback.message.answer(f"💾 Скачиваю фото {img_index + 1}...")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        content = await response.read()

                        with open(filepath, 'wb') as f:
                            f.write(content)

                        # ✅ ИСПРАВЛЕНО - используем FSInputFile
                        photo_file = FSInputFile(filepath)

                        await callback.message.answer_photo(
                            photo=photo_file,  # ← ТАК НУЖНО!
                            caption=(
                                f"✅ <b>Сохранено!</b>\n\n"
                                f"📁 <code>{filename}</code>\n"
                                f"📷 Фото: {img_index + 1} / {total}"
                            ),
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await callback.message.answer(f"❌ Ошибка HTTP {response.status}")

        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            await callback.message.answer(f"❌ Ошибка: {e}")

        await callback.answer("✅ Готово!")

    async def _on_save_all_photos(self, callback):
        """Сохранение ВСЕХ фото"""
        from aiogram.enums import ParseMode
        import os
        import aiohttp

        parts = callback.data.replace('img_all_', '').split('_')

        table_name = parts[0]
        row_num = int(parts[1])
        item_id = int(parts[2])

        # Получаем данные
        data = self._get_row(table_name, row_num)

        if not data:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return

        images_str = data.get('images', '')
        image_urls = [img.strip() for img in images_str.split(';') if img.strip()]

        total = len(image_urls)

        await callback.message.answer(f"💾 Скачиваю все {total} фото...")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'maker_images', 'source_images')
        os.makedirs(save_dir, exist_ok=True)

        saved = 0
        failed = 0

        async with aiohttp.ClientSession() as session:
            for i, url in enumerate(image_urls):

                filename = f"{table_name}_{row_num}_{i + 1}.webp"
                filepath = os.path.join(save_dir, filename)

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            with open(filepath, 'wb') as f:
                                f.write(content)
                            saved += 1
                        else:
                            failed += 1

                except Exception as e:
                    failed += 1

                await asyncio.sleep(0.3)

        await callback.message.answer(
            f"✅ <b>Готово!</b>\n\n"
            f"📁 Папка: <code>maker_images/source_images/</code>\n"
            f"💾 Сохранено: <b>{saved}</b> / {total}\n"
            f"❌ Ошибок: <b>{failed}</b>",
            parse_mode=ParseMode.HTML
        )

        await callback.answer(f"✅ Сохранено {saved} фото!")

    async def cmd_post(self, message):
        from aiogram.enums import ParseMode
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Нет доступа")
            return

        args = message.text.split(maxsplit=2)

        if len(args) < 3:
            await message.answer(
                "❌ Формат:\n<code>/post таблица номер</code>",
                parse_mode=ParseMode.HTML
            )
            return

        table_name = args[1]

        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("❌ Номер — число!")
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await message.answer(
                f"❌ Не найдено: <code>{table_name}</code> строка {row_num}",
                parse_mode=ParseMode.HTML
            )
            return

        post_text = self._format_post(data)
        item_id = data.get('id', '-')

        # === ИЩЕМ ФОТО В ПАПКЕ ===
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'maker_images', 'source_images')

        photo_path = None

        possible_names = [
            f"{table_name}_{row_num}_1.webp",
            f"{item_id}_1.webp",
        ]

        for filename in possible_names:
            filepath = os.path.join(save_dir, filename)
            if os.path.exists(filepath):
                photo_path = filepath
                break

        try:
            if photo_path and os.path.exists(photo_path) and os.path.getsize(photo_path) > 0:
                # ✅ ПРАВИЛЬНЫЙ СПОСОБ - BufferedInputFile!
                with open(photo_path, 'rb') as file:
                    file_data = file.read()

                photo_buffer = BufferedInputFile(file_data, filename=os.path.basename(photo_path))

                msg = await self.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=photo_buffer,
                    caption=post_text,
                    parse_mode=ParseMode.HTML
                )

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Пост",
                            url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                        ),
                        InlineKeyboardButton(text="🗑️", callback_data=f"del_{msg.message_id}")
                    ]
                ])

                await message.answer(
                    f"✅ Опубликовано! 📷\n\n"
                    f"📊 <code>{table_name}</code>\n"
                    f"🔢 Строка: {row_num}\n"
                    f"📁 Фото: <code>{os.path.basename(photo_path)}</code>",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

            else:
                # Без фото
                msg = await self.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅",
                            url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                        ),
                        InlineKeyboardButton(text="🗑️", callback_data=f"del_{msg.message_id}")
                    ]
                ])

                await message.answer(
                    f"✅ Опубликовано! 📝\n\n"
                    f"📊 <code>{table_name}</code>\n"
                    f"🔢 Строка: {row_num}\n\n"
                    f"⚠️  Фото не найдено!\n"
                    f"💡 Сначала: <code>/images {table_name} {row_num}</code>",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            await message.answer(f"❌ Ошибка: {e}")

    async def cmd_preview(self, message):
        from aiogram.enums import ParseMode

        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Нет доступа")
            return

        args = message.text.split(maxsplit=2)

        if len(args) < 3:
            await message.answer("❌ Формат: <code>/preview таблица номер</code>",
                                 parse_mode=ParseMode.HTML)
            return

        table_name = args[1]

        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("❌ Номер — число!")
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await message.answer("❌ Не найдено")
            return

        post_text = self._format_post(data)

        await message.answer(
            f"👁️ <b>PREVIEW</b>\n\n{post_text}",
            parse_mode=ParseMode.HTML
        )

    async def cmd_parsing(self, message):
        from aiogram.enums import ParseMode

        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ Нет доступа")
            return

        if not self._parsing_lock.acquire(blocking=False):
            await message.answer("⏳ Парсинг уже запущен! Дождись окончания.")
            return

        args = message.text.split(maxsplit=1)

        if len(args) < 2:
            self._parsing_lock.release()
            await message.answer(
                "❌ Формат:\n<code>/parsing запрос</code>",
                parse_mode=ParseMode.HTML
            )
            return

        query = args[1].strip()

        status_msg = await message.answer(
            f"🚀 <b>Запускаю парсинг...</b>\n\n"
            f"🔍 Запрос: <code>{query}</code>\n\n"
            f"⏳ Это может занять время...",
            parse_mode=ParseMode.HTML
        )

        def do_parse():
            try:
                from pars.main import parse

                logger.info(f"Запуск парсинга: {query}")
                result = parse(search_phrase=query)

                return {"success": True, "query": query, "result": result}

            except Exception as e:
                logger.error(f"Ошибка парсинга: {e}")
                return {"success": False, "error": str(e)}

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, do_parse)

        while not future.done():
            await asyncio.sleep(3)

        parsing_result = future.result()
        self._parsing_lock.release()

        if parsing_result.get("success"):
            result_data = parsing_result["result"]

            if result_data and len(result_data) > 0:
                table_name = query.lower().replace(' ', '_').replace('-', '_')

                with DatabaseManager() as db:
                    db_count = db.get_count(table_name)

                await status_msg.edit_text(
                    f"✅ <b>ПАРСИНГ ЗАВЕРШЁН!</b>\n\n"
                    f"🔍 Запрос: <code>{query}</code>\n"
                    f"📊 Таблица: <code>{table_name}</code>\n"
                    f"📦 Товаров: <b>{db_count}</b> шт\n\n"
                    f"💡 Постить:\n<code>/post {table_name} 1</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await status_msg.edit_text(
                    f"⚠️ <b>ПАРСИНГ ЗАВЕРШЁН</b>\n\n"
                    f"🔍 Запрос: <code>{query}</code>\n"
                    f"📦 Товаров: <b>0</b>",
                    parse_mode=ParseMode.HTML
                )
        else:
            error = parsing_result.get("error", "Неизвестная ошибка")
            await status_msg.edit_text(
                f"❌ <b>ОШИБКА ПАРСИНГА</b>\n\n{error[:500]}",
                parse_mode=ParseMode.HTML
            )

    # ============================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================

    def _get_row(self, table_name: str, row_num: int) -> dict | None:
        try:
            with DatabaseManager() as db:
                rows = db.get_all(table_name, limit=10000)

                if row_num < 1 or row_num > len(rows):
                    return None

                return rows[row_num - 1]

        except Exception as e:
            logger.error(f"Ошибка _get_row: {e}")
            return None

    def _format_post(self, data: dict) -> str:

        item_id = data.get('id', '-')
        name = data.get('name', 'Без названия')
        brand = data.get('brand', '-')
        price = data.get('price')
        sale_price = data.get('sale_price')
        wb_wallet = data.get('wb_wallet')
        rating = data.get('rating', '-')
        quantity = data.get('quantity', 0)
        supplier = data.get('supplier_name', '-')
        feedbacks = data.get('feedbacks', 0)
        entity = data.get('entity', '')
        link = data.get('link', '#')

        parts = [f"🆔 <b>Артикул: {item_id}</b>"]

        prefix = '🔥' if sale_price else ''
        parts.append(f"\n{prefix} <b>{name}</b>")

        price_lines = []
        if price:
            if sale_price and sale_price != price:
                discount = int(100 - (sale_price / price * 100))
                price_lines.append(
                    f"💰 ~~{int(price):,}~~ → "
                    f"<b>{int(sale_price):,} ₽</b> (-{discount}%)"
                )
                if wb_wallet:
                    price_lines.append(f"🛒 WB кошелёк: <b>{int(wb_wallet):,} ₽</b>")
            else:
                price_lines.append(f"💰 <b>{int(price):,} ₽</b>")

        if price_lines:
            parts.append("\n" + "\n".join(price_lines))

        info = (
            f"\n🏷 Бренд: {brand}"
            f"\n⭐ Рейтинг: {rating} ({feedbacks} отзывов)"
            f"\n📦 В наличии: {quantity} шт"
            f"\n🏪 Продавец: {supplier}"
        )

        if entity:
            info += f"\n📂 Категория: {entity}"

        parts.append(info)

        clean_link = link.replace('\u200B', '')
        parts.append(f"\n\n🔗 <a href=\"{clean_link}\">🛒 ПЕРЕЙТИ НА WILDBERRIES 🛒</a>")

        return "\n".join(parts)

    async def run(self):
        await self._create_bot()

        logger.info("Бот запущен")

        await self.bot.delete_webhook(drop_pending_updates=True)
        await self.dp.start_polling(self.bot)


# ============================================
# ЗАПУСК
# ============================================
if __name__ == '__main__':

    bot = TgPostingBot()

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")