"""Подключение к PostgreSQL"""
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import os
import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с PostgreSQL через connection pool"""
    
    _connection_pool: Optional[pool.SimpleConnectionPool] = None
    
    @classmethod
    def initialize(cls):
        """Инициализация пула подключений"""
        if cls._connection_pool is None:
            try:
                cls._connection_pool = pool.SimpleConnectionPool(
                    minconn=1,
                    maxconn=20,
                    host=os.getenv('POSTGRES_HOST'),
                    port=os.getenv('POSTGRES_PORT', '5432'),
                    database=os.getenv('POSTGRES_DATABASE'),
                    user=os.getenv('POSTGRES_USER'),
                    password=os.getenv('POSTGRES_PASSWORD'),
                    sslmode='require',
                    connect_timeout=10
                )
                logger.info("Database connection pool initialized")
            except Exception as e:
                logger.error(f"Failed to initialize database pool: {e}")
                raise
    
    @classmethod
    @contextmanager
    def get_connection(cls):
        """Context manager для получения подключения из пула"""
        if cls._connection_pool is None:
            cls.initialize()
        
        connection = None
        try:
            connection = cls._connection_pool.getconn()
            yield connection
        except Exception as e:
            if connection:
                connection.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if connection:
                cls._connection_pool.putconn(connection)
    
    @classmethod
    @contextmanager
    def get_cursor(cls, cursor_factory=RealDictCursor):
        """Context manager для получения курсора"""
        with cls.get_connection() as connection:
            cursor = connection.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
                connection.commit()
            except Exception as e:
                connection.rollback()
                logger.error(f"Cursor error: {e}")
                raise
            finally:
                cursor.close()
    
    @classmethod
    def execute_query(cls, query: str, params: tuple = None, fetch: bool = True):
        """Выполнение SQL запроса"""
        with cls.get_cursor() as cursor:
            cursor.execute(query, params or ())
            if fetch:
                return cursor.fetchall()
            return cursor.rowcount
    
    @classmethod
    def execute_one(cls, query: str, params: tuple = None):
        """Выполнение запроса с возвратом одной строки"""
        with cls.get_cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.fetchone()


# Инициализация при импорте
Database.initialize()
