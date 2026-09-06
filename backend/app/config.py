from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    ANTHROPIC_API_KEY: str
    ENVIRONMENT: str = "development"
    VOYAGE_API_KEY: str
    GITHUB_APP_ID: str
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    GITHUB_WEBHOOK_SECRET: str
    GITHUB_PRIVATE_KEY_PATH: str
    GITHUB_TEST_INSTALLATION_ID: str = ""

    class Config:
        env_file = ".env"


settings = Settings()