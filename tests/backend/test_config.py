def test_settings_load_from_environment(settings):
    assert settings.app_name == "Backend Test App"
    assert settings.database_url.endswith("settings.db")
