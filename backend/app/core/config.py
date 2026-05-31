from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str
    secret_key: str = "change-me"


app_settings = AppSettings()
