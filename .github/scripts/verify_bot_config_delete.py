from __future__ import annotations

import os
from pathlib import Path
import tempfile

from darkweb_collector.bot_assistant import (
    BOT_CHAT_ID_ENV,
    BOT_ID_ENV,
    BOT_SECRET_ENV,
    BOT_SETTINGS_PATH_ENV,
    BOT_WEBSOCKET_URL_ENV,
    BOT_WEBHOOK_SECRET_ENV,
    BOT_WEBHOOK_URL_ENV,
    WECHAT_BOT_WEBHOOK_ENV,
    WECHAT_WORK_BOT_SECRET_ENV,
    WECHAT_WORK_BOT_WEBHOOK_ENV,
    bot_config_status,
    delete_bot_config,
    load_bot_config,
    set_bot_config,
)
from darkweb_collector.dingtalk_bot import (
    DINGTALK_SECRET_ENV,
    DINGTALK_SETTINGS_PATH_ENV,
    DINGTALK_WEBHOOK_ENV,
    delete_dingtalk_config,
    dingtalk_config_status,
    load_dingtalk_config,
    set_dingtalk_config,
)


managed_environment = (
    BOT_SETTINGS_PATH_ENV,
    BOT_ID_ENV,
    BOT_SECRET_ENV,
    BOT_CHAT_ID_ENV,
    BOT_WEBSOCKET_URL_ENV,
    BOT_WEBHOOK_URL_ENV,
    BOT_WEBHOOK_SECRET_ENV,
    WECHAT_WORK_BOT_WEBHOOK_ENV,
    WECHAT_WORK_BOT_SECRET_ENV,
    WECHAT_BOT_WEBHOOK_ENV,
    DINGTALK_SETTINGS_PATH_ENV,
    DINGTALK_WEBHOOK_ENV,
    DINGTALK_SECRET_ENV,
    "BOT_PROVIDER",
    "BOT_DRY_RUN",
)
previous_environment = {name: os.environ.get(name) for name in managed_environment}

try:
    with tempfile.TemporaryDirectory(prefix="darkweb-bot-delete-") as temporary:
        root = Path(temporary)
        wecom_path = root / "bot_assistant_settings.json"
        dingtalk_path = root / "dingtalk_bot_settings.json"
        unrelated_path = root / "monitoring-object-data.json"
        unrelated_path.write_text("preserve", encoding="utf-8")
        for name in managed_environment:
            os.environ.pop(name, None)
        os.environ[BOT_SETTINGS_PATH_ENV] = str(wecom_path)
        os.environ[DINGTALK_SETTINGS_PATH_ENV] = str(dingtalk_path)
        os.environ["BOT_DRY_RUN"] = "1"

        set_bot_config(bot_id="saved-bot", secret="saved-secret", chat_id="saved-chat")
        set_dingtalk_config(webhook_url="saved-token", secret="saved-secret")
        assert wecom_path.is_file() and dingtalk_path.is_file()

        wecom_deleted = delete_bot_config()
        assert wecom_deleted["saved_config_deleted"] is True
        assert wecom_deleted["configured"] is False
        assert wecom_deleted["source"] == "none"
        assert not wecom_path.exists()
        assert dingtalk_config_status(load_dingtalk_config())["configured"] is True
        assert unrelated_path.read_text(encoding="utf-8") == "preserve"

        set_bot_config(bot_id="replacement-bot", secret="replacement-secret")
        dingtalk_deleted = delete_dingtalk_config()
        assert dingtalk_deleted["saved_config_deleted"] is True
        assert dingtalk_deleted["configured"] is False
        assert dingtalk_deleted["source"] == "none"
        assert not dingtalk_path.exists()
        assert bot_config_status(load_bot_config())["configured"] is True
        assert unrelated_path.read_text(encoding="utf-8") == "preserve"

        assert delete_bot_config()["saved_config_deleted"] is True
        assert delete_bot_config()["saved_config_deleted"] is False
        assert delete_dingtalk_config()["saved_config_deleted"] is False

        os.environ[BOT_ID_ENV] = "environment-bot"
        os.environ[BOT_SECRET_ENV] = "environment-secret"
        set_bot_config(bot_id="saved-bot", secret="saved-secret")
        wecom_fallback = delete_bot_config()
        assert wecom_fallback["configured"] is True
        assert wecom_fallback["source"] == "environment"

        os.environ[DINGTALK_WEBHOOK_ENV] = "environment-token"
        set_dingtalk_config(webhook_url="saved-token")
        dingtalk_fallback = delete_dingtalk_config()
        assert dingtalk_fallback["configured"] is True
        assert dingtalk_fallback["source"] == "environment"
        assert unrelated_path.read_text(encoding="utf-8") == "preserve"
finally:
    for name, value in previous_environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

print("Independent WeCom and DingTalk deletion checks passed.")

repository_root = Path(__file__).resolve().parents[2]
settings_html = (repository_root / "threat-intelligence-dashboard/src/prototype/screens/settings.html").read_text(
    encoding="utf-8"
)
runtime_js = (repository_root / "threat-intelligence-dashboard/src/prototype/runtime.js").read_text(
    encoding="utf-8"
)
assert 'data-collector-action="bot-delete"' in settings_html
assert 'data-collector-action="dingtalk-delete"' in settings_html
assert "request('/api/bot/config', { method: 'DELETE' })" in runtime_js
assert "request('/api/dingtalk/config', { method: 'DELETE' })" in runtime_js
print("Independent Bot delete buttons are wired to separate endpoints.")
