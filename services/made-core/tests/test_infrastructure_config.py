"""Unit tests for InfrastructureConfig."""

from __future__ import annotations

import os
from unittest import mock

import pytest
from pydantic import ValidationError

from made_core.infrastructure.config import InfrastructureConfig


def test_infrastructure_config_defaults():
    config = InfrastructureConfig()
    assert config.redis_host == "localhost"
    assert config.redis_port == 6379
    assert config.redis_db == 0
    assert config.redis_username is None
    assert config.redis_password is None
    assert config.input_stream == "events:normalized"
    assert config.consumer_group == "made-core-processors"
    assert config.consumer_name == "made-core-worker-1"
    assert config.batch_size == 10
    assert config.block_timeout_ms == 2000
    assert config.dead_letter_stream == "events:dead-letter"
    assert config.get_redis_url() == "redis://localhost:6379/0"


def test_infrastructure_config_env_overrides():
    env_vars = {
        "MADE_REDIS_HOST": "redis.prod.internal",
        "MADE_REDIS_PORT": "6380",
        "MADE_REDIS_DB": "2",
        "MADE_REDIS_PASSWORD": "secretpassword",
        "MADE_INPUT_STREAM": "custom:events",
        "MADE_CONSUMER_GROUP": "custom-group",
        "MADE_CONSUMER_NAME": "custom-worker-99",
        "MADE_BATCH_SIZE": "50",
        "MADE_BLOCK_TIMEOUT_MS": "5000",
        "MADE_DEAD_LETTER_STREAM": "custom:dlq",
    }
    with mock.patch.dict(os.environ, env_vars, clear=False):
        config = InfrastructureConfig()
        assert config.redis_host == "redis.prod.internal"
        assert config.redis_port == 6380
        assert config.redis_db == 2
        assert config.redis_password == "secretpassword"
        assert config.input_stream == "custom:events"
        assert config.consumer_group == "custom-group"
        assert config.consumer_name == "custom-worker-99"
        assert config.batch_size == 50
        assert config.block_timeout_ms == 5000
        assert config.dead_letter_stream == "custom:dlq"
        assert config.get_redis_url() == "redis://:secretpassword@redis.prod.internal:6380/2"


def test_infrastructure_config_with_username_and_password():
    config = InfrastructureConfig(
        redis_host="auth.redis",
        redis_port=6379,
        redis_username="user1",
        redis_password="pass1",
        redis_db=1,
    )
    assert config.get_redis_url() == "redis://user1:pass1@auth.redis:6379/1"


def test_infrastructure_config_explicit_url():
    config = InfrastructureConfig(redis_url="rediss://custom-cluster:6379/0")
    assert config.get_redis_url() == "rediss://custom-cluster:6379/0"


def test_infrastructure_config_invalid_port():
    with pytest.raises(ValidationError):
        InfrastructureConfig(redis_port=70000)

    with pytest.raises(ValidationError):
        InfrastructureConfig(postgres_port=0)


def test_infrastructure_config_invalid_batch_size():
    with pytest.raises(ValidationError):
        InfrastructureConfig(batch_size=0)


def test_infrastructure_config_invalid_telegram_timeout():
    with pytest.raises(ValidationError):
        InfrastructureConfig(telegram_timeout_seconds=-1.0)

