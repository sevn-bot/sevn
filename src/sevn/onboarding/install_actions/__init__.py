"""Install action executors for onboarding capability setup (W6).

Module: sevn.onboarding.install_actions
Depends: sevn.onboarding.install_actions.executors

Exports:
    execute_install_action — run one manifest install action.
    idempotent_check_satisfied — evaluate ``idempotent_check`` before execute.
"""

from sevn.onboarding.install_actions.executors import (
    execute_install_action,
    idempotent_check_satisfied,
)

__all__ = [
    "execute_install_action",
    "idempotent_check_satisfied",
]
