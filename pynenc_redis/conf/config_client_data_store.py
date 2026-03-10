from pynenc.conf.config_client_data_store import ConfigClientDataStore

from pynenc_redis.conf.config_redis import ConfigRedis


class ConfigClientDataStoreRedis(ConfigClientDataStore, ConfigRedis):
    """Specific Configuration for the Redis Argument Cache"""
