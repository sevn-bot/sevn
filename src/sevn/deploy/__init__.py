"""Remote SSH deploy orchestration from ``sevn export-secrets`` bundles.

Module: sevn.deploy
Depends: sevn.deploy.inventory, sevn.deploy.remote, sevn.deploy.report, sevn.deploy.ssh_runner

Exports:
    DeployHost — resolved inventory host entry.
    DeployInventory — loaded TOML inventory document.
    DeployInventoryError — inventory load/validation failure.
    DeployMode — check, dry-run, or full deploy.
    DeployReport — structured deploy outcome.
    DeployRunnerError — orchestration failure with exit code.
    RemoteDeployRunner — SSH deploy step machine.
    SSHCommandError — non-zero ssh/scp exit.
    SSHRunner — subprocess ssh/scp backend.
    load_inventory — parse ``deploy/inventory.toml``.
    resolve_inventory_path — locate inventory file.
    write_deploy_report — persist JSON report under ``reports/``.
"""

from sevn.deploy.inventory import (
    DeployHost,
    DeployInventory,
    DeployInventoryError,
    load_inventory,
    resolve_inventory_path,
)
from sevn.deploy.remote import DeployMode, DeployRunnerError, RemoteDeployRunner
from sevn.deploy.report import DeployReport, write_deploy_report
from sevn.deploy.ssh_runner import SSHCommandError, SSHRunner

__all__ = [
    "DeployHost",
    "DeployInventory",
    "DeployInventoryError",
    "DeployMode",
    "DeployReport",
    "DeployRunnerError",
    "RemoteDeployRunner",
    "SSHCommandError",
    "SSHRunner",
    "load_inventory",
    "resolve_inventory_path",
    "write_deploy_report",
]
