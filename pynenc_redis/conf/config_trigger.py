from pynenc.conf.config_trigger import ConfigTrigger

from pynenc_redis.conf.config_redis import ConfigRedis


class ConfigTriggerRedis(ConfigTrigger, ConfigRedis):
    """Specific Configuration for the Redis Trigger"""
