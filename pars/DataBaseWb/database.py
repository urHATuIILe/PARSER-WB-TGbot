import asyncio
import psycopg
from psycopg import sql
from loguru import logger
import re
from contextlib import asynccontextmanager
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['PGCLIENTENCODING'] = 'UTF8'

from .config_db import PASSWORD


class AsyncDatabaseManager:
    CONFIG = {
        'host': 'localhost',
        'port': 5432,
        'user': 'postgres',
        'password': PASSWORD,
        'dbname': 'wildberries_db'
    }

    def __init__(self):
        self._conn = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _sanitize_name(query: str) -> str:
        name = query.lower().strip()
        name = name.replace(' ', '_')
        name = name.replace('-', '_')
        name = re.sub(r'[^\w]', '', name, flags=re.UNICODE)
        name = re.sub(r'_+', '_', name)
        return name[:63] if name else "query"

    async def connect(self) -> bool:
        try:
            self._conn = await psycopg.AsyncConnection.connect(**self.CONFIG)
            logger.success("Подключились к бд")
            return True
        except psycopg.OperationalError as e:
            logger.error(f"Ошибка подключения {e}")
            return False

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.success("Закрыли бд")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @property
    def connection(self):
        return self._conn

    @asynccontextmanager
    async def cursor(self):
        if not self._conn:
            raise RuntimeError("Нет подключения к БД")
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            await cur.close()

    async def create_table(self, query: str) -> str | None:
        table_name = self._sanitize_name(query)
        logger.info(f"Создаем таблицу {table_name}")

        try:
            async with self._lock:
                async with self.cursor() as cur:
                    await cur.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')

                    await cur.execute(f'''
                        CREATE TABLE "{table_name}" (
                            id INTEGER PRIMARY KEY,
                            link TEXT,
                            name TEXT NOT NULL,
                            price DOUBLE PRECISION,
                            sale_price DOUBLE PRECISION,
                            wb_wallet DOUBLE PRECISION,
                            brand TEXT,
                            rating DOUBLE PRECISION,
                            quantity INTEGER DEFAULT 0,
                            supplier_id INTEGER,
                            supplier_name TEXT,
                            supplier_rating DOUBLE PRECISION,
                            images TEXT,
                            feedbacks INTEGER,
                            entity TEXT
                        )
                    ''')

                    idx_brand = f"idx_{table_name}_brand"
                    idx_price = f"idx_{table_name}_price"

                    await cur.execute(f'CREATE INDEX IF NOT EXISTS "{idx_brand}" ON "{table_name}"(brand)')
                    await cur.execute(f'CREATE INDEX IF NOT EXISTS "{idx_price}" ON "{table_name}"(price)')

                    await self._conn.commit()

            logger.success(f"Таблица '{table_name}' создана")
            return table_name

        except Exception as e:
            logger.error(f"Ошибка создания таблицы: {e}")
            if self._conn:
                await self._conn.rollback()
            return None

    def _item_to_dict(self, item) -> dict:
        link = f"\u200Bhttps://www.wildberries.ru/catalog/{item.id}/detail.aspx"

        return {
            'id': item.id,
            'link': link,
            'name': item.name,
            'price': item.priceU,
            'sale_price': item.salePriceU,
            'wb_wallet': item.wb_wallet,
            'brand': item.brand,
            'rating': item.nmReviewRating,
            'quantity': item.totalQuantity,
            'supplier_id': item.supplierId,
            'supplier_name': item.supplier,
            'supplier_rating': item.supplierRating,
            'images': item.image_links,
            'feedbacks': item.nmFeedbacks,
            'entity': item.entity
        }

    async def insert_product(self, table_name: str, item) -> bool:
        try:
            data = self._item_to_dict(item) if hasattr(item, 'id') else item

            async with self.cursor() as cur:
                await cur.execute(f'''
                    INSERT INTO "{table_name}" 
                    (id, link, name, price, sale_price, wb_wallet, 
                     brand, rating, quantity, supplier_id, 
                     supplier_name, supplier_rating, images, feedbacks, entity)
                    VALUES (
                        %(id)s, %(link)s, %(name)s, %(price)s, 
                        %(sale_price)s, %(wb_wallet)s, %(brand)s, 
                        %(rating)s, %(quantity)s, %(supplier_id)s, 
                        %(supplier_name)s, %(supplier_rating)s, 
                        %(images)s, %(feedbacks)s, %(entity)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        price = EXCLUDED.price,
                        sale_price = EXCLUDED.sale_price
                ''', data)

                await self._conn.commit()
                return True

        except Exception as e:
            logger.error(f"Ошибка вставки: {e}")
            if self._conn:
                await self._conn.rollback()
            return False

    async def insert_many(self, table_name: str, items: list) -> int:
        if not items:
            return 0

        count = 0

        try:
            async with self.cursor() as cur:
                for item in items:
                    data = self._item_to_dict(item) if hasattr(item, 'id') else item

                    await cur.execute(f'''
                        INSERT INTO "{table_name}" 
                        (id, link, name, price, sale_price, wb_wallet, 
                         brand, rating, quantity, supplier_id, 
                         supplier_name, supplier_rating, images, feedbacks, entity)
                        VALUES (
                            %(id)s, %(link)s, %(name)s, %(price)s, 
                            %(sale_price)s, %(wb_wallet)s, %(brand)s, 
                            %(rating)s, %(quantity)s, %(supplier_id)s, 
                            %(supplier_name)s, %(supplier_rating)s, 
                            %(images)s, %(feedbacks)s, %(entity)s
                        )
                        ON CONFLICT (id) DO NOTHING
                    ''', data)

                    count += 1

                await self._conn.commit()

            logger.success(f"Вставлено {count} товаров в '{table_name}'")
            return count

        except Exception as e:
            logger.error(f"Ошибка массовой вставки: {e}")
            if self._conn:
                await self._conn.rollback()
            return 0

    async def insert_many_batch(self, table_name: str, items: list, batch_size=1000) -> int:
        if not items:
            return 0

        total_count = 0

        try:
            data_list = [
                self._item_to_dict(item) if hasattr(item, 'id') else item
                for item in items
            ]

            async with self.cursor() as cur:
                for i in range(0, len(data_list), batch_size):
                    batch = data_list[i:i + batch_size]

                    await cur.executemany(f'''
                        INSERT INTO "{table_name}" 
                        (id, link, name, price, sale_price, wb_wallet, 
                         brand, rating, quantity, supplier_id, 
                         supplier_name, supplier_rating, images, feedbacks, entity)
                        VALUES (
                            %(id)s, %(link)s, %(name)s, %(price)s, 
                            %(sale_price)s, %(wb_wallet)s, %(brand)s, 
                            %(rating)s, %(quantity)s, %(supplier_id)s, 
                            %(supplier_name)s, %(supplier_rating)s, 
                            %(images)s, %(feedbacks)s, %(entity)s
                        )
                        ON CONFLICT (id) DO NOTHING
                    ''', batch)

                    total_count += len(batch)

                await self._conn.commit()

            logger.success(f"Вставлено {total_count} товаров в '{table_name}'")
            return total_count

        except Exception as e:
            logger.error(f"Ошибка пакетной вставки: {e}")
            if self._conn:
                await self._conn.rollback()
            return 0

    async def get_all(self, table_name: str, limit: int = 100) -> list[dict]:
        try:
            async with self.cursor() as cur:
                await cur.execute(f'SELECT * FROM "{table_name}" ORDER BY id LIMIT %s', (limit,))
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in await cur.fetchall()]
        except Exception as e:
            logger.error(f"Ошибка получения данных: {e}")
            return []

    async def get_count(self, table_name: str) -> int:
        try:
            async with self.cursor() as cur:
                await cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                result = await cur.fetchone()
                return result[0]
        except Exception as e:
            logger.error(f"Ошибка подсчёта: {e}")
            return 0

    async def list_tables(self) -> list[str]:
        try:
            async with self.cursor() as cur:
                await cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
                return [row[0] for row in await cur.fetchall()]
        except Exception as e:
            logger.error(f"Ошибка получения списка таблиц: {e}")
            return []


DatabaseManager = AsyncDatabaseManager