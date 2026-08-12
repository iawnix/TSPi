"""Deterministic, installation-configured TS user notifications."""

from .delivery import EmailNotificationConfig, load_notification_config, notify_user

__all__ = ["EmailNotificationConfig", "load_notification_config", "notify_user"]
