
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
            "/tables — список таблиц",
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
                "❌ Формат:\n<code>/parsing запрос</code>\n\n"
                "Пример:\n<code>/parsing футболка radiohead</code>",
                parse_mode=ParseMode.HTML
            )
            return

        query = args[1].strip()

        status_msg = await message.answer(
            f"🚀 <b>Запускаю парсинг...</b>\n\n"
            f"🔍 Запрос: <code>{query}</code>\n\n"
            f"⏳ Это может занять 1-5 минут...",
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
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, do_parse)

        parsing_result = None

        while not future.done():
            await asyncio.sleep(3)

        parsing_result = future.result()
        self._parsing_lock.release()

        if parsing_result.get("success"):
            result_data = parsing_result["result"]

            if result_data and len(result_data) > 0:

                table_name = query.lower().replace(' ', '_').replace('-', '_')

                count = len(result_data)

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
                    f"📦 Товаров: <b>0</b>\n\n"
                    f"Товаров не найдено.",
                    parse_mode=ParseMode.HTML
                )
        else:
            error = parsing_result.get("error", "Неизвестная ошибка")
            await status_msg.edit_text(
                f"❌ <b>ОШИБКА ПАРСИНГА</b>\n\n"
                f"🔍 Запрос: <code>{query}</code>\n\n"
                f"<code>{error[:500]}</code>",
                parse_mode=ParseMode.HTML
            )

    async def cmd_post(self, message):
        from aiogram.enums import ParseMode
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

        try:
            msg = await self.bot.send_message(
                chat_id=CHANNEL_ID,
                text=post_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Пост",
                        url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                    ),
                    InlineKeyboardButton(
                        text="🗑️",
                        callback_data=f"del_{msg.message_id}"
                    )
                ]
            ])

            await message.answer(
                f"✅ Опубликовано!\n"
                f"📊 <code>{table_name}</code>\n"
                f"🔢 Строка: {row_num}",
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
        supplier_rating = data.get('supplier_rating', '-')
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


if __name__ == '__main__':

    bot = TgPostingBot()

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")