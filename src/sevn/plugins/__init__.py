"""Plugin loading and hook contracts.

Module: sevn.plugins
Depends: sevn.plugins.hook, sevn.plugins.registry, sevn.plugins.runner

Exports:
    Block — hook rejection result.
    Continue — hook allow result.
    HookContext — hook call context.
    PluginHook — hook protocol.
    PluginHookBase — default safe implementations.
    Replace — hook argument substitution result.
    PluginCommandSpec — validated slash row model.
    PluginSlashBinding — dispatcher binding.
    PluginHookChain — ordered hook execution.
    load_plugin_hook_chain — setuptools ``sevn.plugin_hooks`` loader.
"""

from __future__ import annotations

from sevn.plugins.command_spec import PluginCommandSpec, PluginSlashBinding
from sevn.plugins.hook import (
    Block,
    Continue,
    HookContext,
    PluginHook,
    PluginHookBase,
    Replace,
)
from sevn.plugins.registry import (
    build_trigger_mux,
    collect_plugin_slash_bindings,
    load_channel_plugin_classes,
    load_plugin_hook_chain,
    order_hooks_by_runs_after,
    valid_hook_name,
)
from sevn.plugins.runner import PluginHookChain, RegisteredHook
from sevn.plugins.trigger_mux import TriggerPluginHooksMux

__all__ = [
    "Block",
    "Continue",
    "HookContext",
    "PluginCommandSpec",
    "PluginHook",
    "PluginHookBase",
    "PluginHookChain",
    "PluginSlashBinding",
    "RegisteredHook",
    "Replace",
    "TriggerPluginHooksMux",
    "build_trigger_mux",
    "collect_plugin_slash_bindings",
    "load_channel_plugin_classes",
    "load_plugin_hook_chain",
    "order_hooks_by_runs_after",
    "valid_hook_name",
]
