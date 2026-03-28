"""Entrypoint wiring tests for Ops Hub."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from ops_hub import main as main_module


def test_suppress_insecure_request_warnings_only_when_verify_ssl_is_false() -> None:
    with patch.object(main_module.urllib3, "disable_warnings") as disable_warnings:
        main_module._suppress_insecure_request_warnings(verify_ssl=True)
        main_module._suppress_insecure_request_warnings(verify_ssl=None)

    disable_warnings.assert_not_called()

    with patch.object(main_module.urllib3, "disable_warnings") as disable_warnings:
        main_module._suppress_insecure_request_warnings(verify_ssl=False)

    disable_warnings.assert_called_once_with(main_module.urllib3.exceptions.InsecureRequestWarning)


def test_main_builds_and_runs_bot() -> None:
    calls: list[tuple[str, object]] = []

    class _Settings:
        log_level = "INFO"
        environment = "dev"
        discord_token = "token"
        bluefolder_verify_ssl = False

        def validate_or_raise(self) -> None:
            calls.append(("validate", None))

    class _Bot:
        def run(self, token: str) -> None:
            calls.append(("run", token))

    settings = _Settings()
    container = SimpleNamespace(name="container")
    bot = _Bot()
    api_server = SimpleNamespace(start=lambda: calls.append(("api_start", None)), stop=lambda: calls.append(("api_stop", None)))

    with patch.object(main_module, "load_settings", return_value=settings):
        with patch.object(main_module, "configure_logging", side_effect=lambda level: calls.append(("logging", level))):
            with patch.object(main_module, "build_container", return_value=container) as build_container:
                with patch.object(main_module, "build_bot", return_value=bot) as build_bot:
                    with patch.object(main_module, "build_api_server", return_value=api_server) as build_api_server:
                        with patch.object(main_module, "_suppress_insecure_request_warnings") as suppress:
                            assert main_module.main() == 0

    assert calls == [("logging", "INFO"), ("validate", None), ("api_start", None), ("run", "token"), ("api_stop", None)]
    suppress.assert_called_once_with(verify_ssl=False)
    build_container.assert_called_once_with(settings)
    build_bot.assert_called_once_with(settings=settings, container=container)
    build_api_server.assert_called_once_with(settings=settings, container=container)


def test_main_reraises_bot_run_failure() -> None:
    class _Settings:
        log_level = "INFO"
        environment = "dev"
        discord_token = "token"
        bluefolder_verify_ssl = True

        def validate_or_raise(self) -> None:
            return None

    class _Bot:
        def run(self, token: str) -> None:
            raise RuntimeError("boom")

    settings = _Settings()
    api_server = SimpleNamespace(start=lambda: None, stop=lambda: None)

    with patch.object(main_module, "load_settings", return_value=settings):
        with patch.object(main_module, "configure_logging"):
            with patch.object(main_module, "build_container", return_value=SimpleNamespace()):
                with patch.object(main_module, "build_bot", return_value=_Bot()):
                    with patch.object(main_module, "build_api_server", return_value=api_server):
                        with patch.object(main_module, "_suppress_insecure_request_warnings"):
                            try:
                                main_module.main()
                            except RuntimeError as exc:
                                assert str(exc) == "boom"
                            else:
                                raise AssertionError("Expected main() to re-raise bot runtime failures")
