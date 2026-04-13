"""Validate litellm_config.yaml structure and settings."""


def test_litellm_config_is_valid_yaml(litellm_config_data):
    assert isinstance(litellm_config_data, dict)


def test_litellm_config_has_model_list(litellm_config_data):
    assert "model_list" in litellm_config_data


def test_litellm_config_has_general_settings(litellm_config_data):
    assert "general_settings" in litellm_config_data


def test_master_key_reads_from_env(litellm_config_data):
    settings = litellm_config_data["general_settings"]
    assert settings.get("master_key") == "os.environ/LITELLM_MASTER_KEY"


def test_database_url_reads_from_env(litellm_config_data):
    settings = litellm_config_data["general_settings"]
    assert settings.get("database_url") == "os.environ/DATABASE_URL"


def test_store_model_in_db_enabled(litellm_config_data):
    settings = litellm_config_data["general_settings"]
    assert settings.get("store_model_in_db") is True
