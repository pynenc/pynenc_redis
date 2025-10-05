from pynenc.conf.config_arg_cache import ConfigArgCache

from pynenc_redis.conf.config_redis import ConfigRedis


class ConfigArgCacheRedis(ConfigArgCache, ConfigRedis):
    """Specific Configuration for the Redis Argument Cache"""
