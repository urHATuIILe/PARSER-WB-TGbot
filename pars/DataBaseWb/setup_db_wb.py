import os
import asyncio

os.environ['PGCLIENTENCODING'] = 'UTF8'

from psycopg import sql
from psycopg import AsyncConnection
from loguru import logger
from config_db import PASSWORD


async def create_database_wb_async():
    logger.info('Создаем бдшку')
    logger.info("Подключаемся к бд")

    conn = None

    try:
        conn = await AsyncConnection.connect(
            host="localhost",
            port="5432",
            user="postgres",
            password=PASSWORD,
            dbname="postgres"
        )

        logger.info("Подключились к бд")

    except Exception as e:
        logger.error(f"Ошибка подключения: {e}")
        return False

    logger.info("Настройка параметров")

    await conn.set_autocommit(True)
    db_name = "wildberries_db"

    logger.info("Создаем БД...")

    try:
        async with conn.cursor() as cursor:
            await cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_name,)
            )

            exists = await cursor.fetchone()

            if exists:
                logger.info("Бд есть. Удаляем")
                await cursor.execute(
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name))
                )

            await cursor.execute(
                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(
                    sql.Identifier(db_name)
                )
            )
            logger.info(f"Создали БД {db_name}")

    except Exception as e:
        logger.error(f"Ошибка при создании БД: {e}")
        if conn:
            await conn.close()
        return False

    if conn:
        await conn.close()

    return True


def create_database_wb():
    return asyncio.run(create_database_wb_async())


if __name__ == '__main__':
    asyncio.run(create_database_wb_async())