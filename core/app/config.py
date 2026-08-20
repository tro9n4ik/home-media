from __future__ import annotations
import secrets
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # База данных
    database_url: str = "postgresql+psycopg://hm:hm@localhost:5432/home_media"

    # Секрет сессий — генерируется при первом старте если не задан
    secret_key: str = ""

    # Путь к данным внутри контейнера ядра
    data_dir: str = "/app/data"

    # Зеркало PyPI — меняется через .env если нужно
    pip_index_url: str = "https://pypi.org/simple/"

    # URL ядра для межплагинного взаимодействия (передаётся плагинам)
    core_internal_url: str = "http://127.0.0.1:8142"

    def effective_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        # Генерируем и сохраняем на диск чтобы пережить перезапуск
        import os
        key_file = os.path.join(self.data_dir, ".secret_key")
        if os.path.exists(key_file):
            return open(key_file).read().strip()
        key = secrets.token_hex(32)
        os.makedirs(self.data_dir, exist_ok=True)
        open(key_file, "w").write(key)
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
