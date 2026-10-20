from dotenv import dotenv_values
import pytest
from scripts.configure_gemini_gui import save_key


def test_hidden_setup_preserves_existing_google_config_and_stores_key_only_locally(tmp_path, capsys):
    path = tmp_path / ".env"
    path.write_text("GOOGLE_OAUTH_CLIENT_ID=keep-me\nAPP_BASE_URL=http://127.0.0.1:8765\n", encoding="utf-8")
    fake = "fake-only-unit-test-key-1234567890"
    save_key(fake, path)
    values = dotenv_values(path)
    assert values["GEMINI_API_KEY"] == fake
    assert values["GEMINI_MODEL"] == "gemini-3.8-flash"
    assert values["AGENT_MODE"] == "gemini"
    assert values["GOOGLE_OAUTH_CLIENT_ID"] == "keep-me"
    assert fake not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["short", "not a valid api key because of spaces"])
def test_invalid_key_does_not_create_env(tmp_path, value):
    path = tmp_path / ".env"
    with pytest.raises(ValueError):
        save_key(value, path)
    assert not path.exists()


def test_replacing_key_keeps_previously_working_model(tmp_path):
    path = tmp_path / ".env"
    path.write_text("GEMINI_MODEL=gemini-3.5-flash\n", encoding="utf-8")
    save_key("fake-only-unit-test-key-1234567890", path)
    assert dotenv_values(path)["GEMINI_MODEL"] == "gemini-3.5-flash"
