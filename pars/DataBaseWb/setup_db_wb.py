import os

os.environ['PGCLIENTENCODING'] = 'UTF8'

from psycopg import sql, connect as pg_connect
from loguru import logger
from config_db import PASSWORD


def create_database_wb():
    logger.info('Создаем бдшку')
    logger.info("Подключаемся к бд")

    try:
        conn = pg_connect(
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

    conn.autocommit = True
    cursor = conn.cursor()
    db_name = "wildberries_db"

    logger.info("Создаем БД...")

    try:
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (db_name,)
        )

        exists = cursor.fetchone()

        if exists:
            logger.info("Бд есть. Удаляем")
            cursor.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name))
            )

        cursor.execute(
            sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(
                sql.Identifier(db_name)
            )
        )
        logger.info(f"Создали БД {db_name}")

    except Exception as e:
        logger.error(f"Ошибка при создании БД: {e}")
        cursor.close()
        conn.close()
        return False

    cursor.close()
    conn.close()

    return True


if __name__ == '__main__':
    create_database_wb()