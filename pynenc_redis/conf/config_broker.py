from pynenc.conf.config_broker import ConfigBroker

from pynenc_redis.conf.config_redis import ConfigRedis


class ConfigBrokerRedis(ConfigBroker, ConfigRedis):
    """Specific Configuration for the Redis Broker"""
