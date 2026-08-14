from pathlib import Path


def test_public_proxies_hide_internal_telegram_prefix() -> None:
    nginx = Path("infra/reverse-proxy/nginx.conf").read_text()
    caddy = Path("infra/deployment/test-server/Caddyfile.example").read_text()
    installer = Path("scripts/test-server-installer-lib.sh").read_text()
    prefix = "/api/v1/internal/telegram"
    assert nginx.index(prefix) < nginx.index("location /api/")
    assert "return 404" in nginx
    for configuration in (caddy, installer):
        assert f"path {prefix} {prefix}/*" in configuration
        assert "respond @telegram_internal 404" in configuration
