"""Static invariants over docker-compose.yml.

The worker image baked `ENTRYPOINT ["/entrypoint.sh"]` which hardcodes
`exec celery worker`. A `command:` directive on services using that image
is silently ignored — beat-as-scheduler quietly ran as beat-as-second-
worker for 3 days, processing user tasks on a stale state image. These
tests pin the override pattern so the next person who adds a beat-style
sibling service can't repeat the mistake.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"


@pytest.fixture
def compose_text() -> str:
    return COMPOSE.read_text()


def _services_using_image(text: str, image_keyword: str) -> dict[str, str]:
    """Return {service_name: full_service_block} for services whose image:
    line contains `image_keyword`."""
    services: dict[str, str] = {}
    # crude but sufficient: split on lines starting with two-space service name
    blocks = re.split(r'^  (\w+):\s*$', text, flags=re.MULTILINE)
    # blocks alternates: prefix, name1, body1, name2, body2, ...
    for i in range(1, len(blocks), 2):
        name, body = blocks[i], blocks[i + 1]
        if image_keyword in body:
            services[name] = body
    return services


def test_beat_overrides_entrypoint_so_it_does_not_run_as_worker(compose_text):
    """The beat service uses the worker image whose ENTRYPOINT hardcodes
    `celery worker`. It MUST set its own `entrypoint:` to override —
    `command:` alone is silently swallowed."""
    services = _services_using_image(compose_text, "subtitles-generator-worker")
    assert "beat" in services, "beat service missing from docker-compose.yml"
    beat = services["beat"]
    assert "entrypoint:" in beat, (
        "beat service uses the worker image (ENTRYPOINT=/entrypoint.sh which "
        "hardcodes `celery worker`). A `command:` directive alone is silently "
        "ignored — beat would actually run as a second worker. Set `entrypoint:` "
        'to e.g. ["celery", "-A", "app.worker.celery_app.celery_app", "beat", '
        '"-l", "info"] to override.'
    )
    assert "beat" in beat, (
        "beat service entrypoint must include the `beat` subcommand, not `worker`."
    )


def test_no_service_uses_command_alone_to_override_worker_entrypoint(compose_text):
    """Any service using the worker image must either:
      (a) inherit the default entrypoint (run as a worker — fine), OR
      (b) override `entrypoint:` to run something else.

    Using `command:` alone is the silent-fail footgun.
    """
    services = _services_using_image(compose_text, "subtitles-generator-worker")
    violations: list[str] = []
    for name, body in services.items():
        has_command = bool(re.search(r'^\s+command:', body, flags=re.MULTILINE))
        has_entrypoint = bool(re.search(r'^\s+entrypoint:', body, flags=re.MULTILINE))
        if has_command and not has_entrypoint:
            violations.append(name)
    assert violations == [], (
        f"services {violations} use `command:` to override the worker image's "
        f"behavior but didn't also set `entrypoint:`. The image's ENTRYPOINT "
        f"hardcodes `celery worker` and ignores `command:` — the service will "
        f"silently run as a worker. Use `entrypoint:` to override."
    )
