"""Montages communs : intégrations personnalisées permises, faux service Folonia."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_socket

from .fake_folonia import FakeFolonia


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Home Assistant ne charge une intégration personnalisée que si on le lui permet."""


@pytest.fixture
async def folonia(request: pytest.FixtureRequest) -> AsyncIterator[tuple[FakeFolonia, str]]:
    # Le banc de Home Assistant ferme les sockets à chaque test. Selon l'ordre de chargement
    # des greffons (il diffère sous macOS), il passe après `pytest-socket` et annule la
    # marque `enable_socket` : on la rétablit ici, juste avant d'ouvrir le faux service.
    if request.node.get_closest_marker("enable_socket"):
        pytest_socket.enable_socket()
    fake = FakeFolonia()
    url = await fake.start()
    yield fake, url
    await fake.stop()
