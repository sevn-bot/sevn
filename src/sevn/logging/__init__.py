"""Daemon service logging (loguru sinks and rotate-on-restart).

Module: sevn.logging
Depends: loguru

Exports:
    (none) — import ``sevn.logging.setup`` for ``setup_service_logging`` and
    ``rotate_active_log_on_restart``.

Examples:
    >>> import sevn.logging
    >>> sevn.logging.__doc__ is not None
    True
"""
