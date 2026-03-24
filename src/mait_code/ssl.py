"""SSL setup for corporate proxy environments (e.g. Netskope).

Injects the OS trust store into Python's ssl module so that
corporate proxy CA certificates are trusted automatically.
"""

import logging

logger = logging.getLogger(__name__)

_injected = False


def setup_ssl() -> None:
    """Inject the OS trust store into Python's ssl module.

    Safe to call multiple times — only injects once. Fails silently
    if truststore is unavailable or injection fails.
    """
    global _injected
    if _injected:
        return

    try:
        import truststore

        truststore.inject_into_ssl()
        _injected = True
        logger.debug("truststore injected OS trust store into ssl")
    except ImportError:
        logger.debug("truststore not installed, skipping OS trust store injection")
    except Exception as e:
        logger.debug("truststore injection failed: %s", e)
