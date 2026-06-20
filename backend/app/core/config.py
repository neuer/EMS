"""集中配置：从环境变量 / .env 读取，统一对外提供 settings 单例。

红线对应：
- 配置集中化（.env）；EMS 凭据等敏感项加密存储（见 crypto.py），此处仅放运行期密钥。
- 时间统一：默认时区 Asia/Shanghai，存储仍以 UTC。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 内置占位默认值（仅允许在开发/测试环境使用）。非开发环境若仍为这些值 → 启动即拒绝。
# 集中定义以保证「字段默认值」与「fail-fast 校验」的单一事实源。
_DEFAULT_JWT_SECRET = "change-me-in-production"
_DEFAULT_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
_DEFAULT_ADMIN_PASSWORD = "admin123"
_DEFAULT_EMS_PASSWORD = "123456"

# 视为「开发/测试」的环境名（这些环境允许使用内置默认值，便于离线联调与单测）
_DEV_ENVIRONMENTS = frozenset({"development", "dev", "test", "testing", "local"})


class Settings(BaseSettings):
    """应用配置。所有字段均可由同名大写环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 应用 ----
    app_name: str = "动环监控预警平台"
    environment: str = "development"
    timezone: str = "Asia/Shanghai"
    log_level: str = "INFO"

    # ---- PostgreSQL / TimescaleDB ----
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "dcim"
    postgres_password: str = "dcim_pass"
    postgres_db: str = "dcim"

    # ---- Redis ----
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # ---- JWT / 登录态 ----
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # ---- 对称加密（Fernet，用于 EMS 凭据加密入库）----
    # 必须为 urlsafe base64 的 32 字节密钥；此默认值仅为占位，
    # 生产务必用 crypto.generate_key() 更换。
    encryption_key: str = _DEFAULT_ENCRYPTION_KEY

    # ---- 默认管理员（首次启动 seed）----
    default_admin_username: str = "admin"
    default_admin_password: str = _DEFAULT_ADMIN_PASSWORD

    # ---- EMS 连接默认值（首次启动 seed 到 ems_config；密码加密入库）----
    ems_base_url: str = "http://ems_mock:9000"
    ems_username: str = "admin"
    ems_password: str = _DEFAULT_EMS_PASSWORD
    ems_recv_ip: str = "backend"
    ems_recv_port: str = "8000"
    ems_version: str = "20170714124155"
    ems_auto_connect: bool = True  # 启动时自动拉起连接管理

    # ---- EMS 运行参数（红线：外部 HTTP 必须配置连接/读取超时）----
    ems_connect_timeout: float = 5.0
    ems_read_timeout: float = 10.0
    ems_heartbeat_interval: int = 20  # 心跳 20s
    ems_max_backoff: int = 60  # 重连指数退避上限
    ems_sync_batch_size: int = 50  # get_spot_list 分批大小

    @model_validator(mode="after")
    def _reject_insecure_defaults(self) -> Settings:
        """红线 #9 安全 fail-fast：非开发环境禁止沿用内置默认密钥/口令。

        缺省占位的 jwt_secret 会让攻击者伪造任意角色 JWT 绕过 RBAC；占位
        encryption_key 使 EMS 凭据「加密」形同虚设。故生产环境若未显式覆盖，
        应用启动即失败，而非静默带病运行。
        """
        if self.environment.strip().lower() in _DEV_ENVIRONMENTS:
            return self
        insecure: list[str] = []
        if self.jwt_secret == _DEFAULT_JWT_SECRET:
            insecure.append("JWT_SECRET")
        if self.encryption_key == _DEFAULT_ENCRYPTION_KEY:
            insecure.append("ENCRYPTION_KEY")
        if self.default_admin_password == _DEFAULT_ADMIN_PASSWORD:
            insecure.append("DEFAULT_ADMIN_PASSWORD")
        if self.ems_password == _DEFAULT_EMS_PASSWORD:
            insecure.append("EMS_PASSWORD")
        if insecure:
            raise ValueError(
                f"environment={self.environment} 下禁止使用内置默认密钥/口令，"
                f"请通过环境变量显式覆盖：{', '.join(insecure)}"
            )
        return self

    @property
    def database_url(self) -> str:
        """应用异步连接串（asyncpg）。"""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Alembic 同步连接串（psycopg2）。"""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
