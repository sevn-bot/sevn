"""Prod-readiness Batch B W6 RED - single build-stamped sandbox image constant (C4.1, C4.3; D42).

Contracts (``about-sevn.bot/specs/08-sandbox.md``):
- No mutable-tag default (``:dev``, ``:latest``, or non-digest) survives under ``src/``.
- One module constant feeds the three former literal sites (D42).
- Schema either defines ``sandbox.docker_image`` or documents that only ``rlm.docker_image``
  is honoured — a plausible silent no-op key is the defect.

W6.1-W6.3 green after W7; W6.4-W6.7 green after W8 (sibling suite).

Digest-cache isolation for spawn suites lives in ``tests/sandbox/conftest.py`` (D43 —
do not edit ``test_post_audit_image_pin_w4_red.py``).
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

from sevn.agent.runtimes.sandbox import _default_repl_image
from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.sandbox_runtime import DockerSandboxRuntime, make_runtime_for_driver
from sevn.workspace.layout import WorkspaceLayout

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_SCHEMA = _REPO / "infra" / "sevn.schema.json"
_MUTABLE_TAG_RE = re.compile(
    r"""ghcr\.io/sevn-bot/sevn/sandbox:(?!@)(?P<tag>dev|latest|[A-Za-z0-9._-]+)""",
)
_LITERAL_SITES = (
    _REPO / "src" / "sevn" / "security" / "sandbox_runtime.py",
    _REPO / "src" / "sevn" / "agent" / "runtimes" / "sandbox.py",
)


def _mutable_sandbox_image_hits() -> list[str]:
    hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _MUTABLE_TAG_RE.finditer(text):
            rel = path.relative_to(_REPO)
            line_no = text.count("\n", 0, match.start()) + 1
            hits.append(f"{rel}:{line_no}:{match.group(0)}")
    return hits


def _import_default_sandbox_image() -> str:
    """W7 deliverable — single build-stamped digest constant (D42)."""
    from sevn.security.sandbox_runtime import DEFAULT_SANDBOX_IMAGE

    return DEFAULT_SANDBOX_IMAGE


def test_w6_1_no_mutable_tag_literals_under_src() -> None:
    """C4.1 / C4.3 — deleting the digest constant and reintroducing ``:dev`` must fail this."""
    hits = _mutable_sandbox_image_hits()
    assert not hits, "mutable sandbox image tags remain under src/:\n" + "\n".join(hits)
    constant = _import_default_sandbox_image()
    assert isinstance(constant, str)
    assert constant.strip()
    assert "@sha256:" in constant, f"default must be digest-pinned, got {constant!r}"
    assert ":dev" not in constant
    assert not constant.rstrip("/").endswith(":latest")


def test_w6_2_three_sites_resolve_from_same_constant(tmp_path: Path) -> None:
    """D42 — ``sandbox_runtime`` default, factory fallback, and REPL default share one object."""
    constant = _import_default_sandbox_image()
    assert "@sha256:" in constant

    image_param = inspect.signature(DockerSandboxRuntime.__init__).parameters["image"]
    assert image_param.default == constant

    cfg = WorkspaceConfig.minimal()
    assert _default_repl_image(cfg) == constant

    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    from sevn.security.sandbox_runtime import SandboxDriver

    rt = make_runtime_for_driver(SandboxDriver.docker, layout=layout, cfg=cfg)
    assert isinstance(rt, DockerSandboxRuntime)
    assert rt._image == constant

    # Source-level: the three former literal sites must reference the constant name, not a tag.
    for path in _LITERAL_SITES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "sandbox:dev" not in node.value, (
                    f"{path.relative_to(_REPO)} still embeds mutable tag {node.value!r}"
                )


def test_w6_3_schema_defines_or_documents_sandbox_docker_image() -> None:
    """D42 — either honour ``sandbox.docker_image`` or document that only ``rlm.docker_image`` is."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    sandbox = schema["properties"]["sandbox"]
    sandbox_props = sandbox.get("properties") or {}
    rlm = schema["properties"]["rlm"]
    rlm_props = rlm.get("properties") or {}
    assert "docker_image" in rlm_props, "rlm.docker_image must remain the override"

    has_sandbox_key = "docker_image" in sandbox_props
    sandbox_blob = json.dumps(sandbox)
    documents_rlm_only = any(
        needle in sandbox_blob.lower()
        for needle in (
            "rlm.docker_image",
            "only rlm.docker_image",
            "not honoured",
            "not honored",
            "does not exist",
            "not a valid key",
            "use rlm.docker_image",
        )
    )
    assert has_sandbox_key or documents_rlm_only, (
        "schema must define sandbox.docker_image or document that only rlm.docker_image is honoured"
    )


def test_w6_3b_require_stamped_reads_assignment_not_substring(tmp_path: Path) -> None:
    """Release ``--require-stamped`` must ignore comment/sentinel ``UNSTAMPED`` substrings."""
    import importlib.util

    script = _REPO / "scripts" / "check_sandbox_mutable_image_tags.py"
    spec = importlib.util.spec_from_file_location("check_sandbox_mutable_image_tags", script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    stamped = tmp_path / "sandbox_runtime.py"
    digest = "sha256:" + ("ab" * 32)
    stamped.write_text(
        "\n".join(
            [
                "# still mentions sha256:UNSTAMPED in a comment",
                '_UNSTAMPED_SANDBOX_DIGEST: Final[str] = "sha256:UNSTAMPED"',
                f'_SANDBOX_IMAGE_DIGEST_STAMP: str = "{digest}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkey_runtime = mod._RUNTIME_MODULE
    mod._RUNTIME_MODULE = stamped
    try:
        assert not mod._stamp_is_missing()
        unstamped = tmp_path / "unstamped.py"
        unstamped.write_text(
            '_SANDBOX_IMAGE_DIGEST_STAMP: str = "sha256:UNSTAMPED"\n',
            encoding="utf-8",
        )
        mod._RUNTIME_MODULE = unstamped
        assert mod._stamp_is_missing()
    finally:
        mod._RUNTIME_MODULE = monkey_runtime


def test_w6_3c_publish_ghcr_stamps_sandbox_digest_before_gateway_builds() -> None:
    """Release publish must stamp from sandbox digest before gateway artifacts COPY src/."""
    import yaml

    workflow = yaml.safe_load(
        (_REPO / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["publish-ghcr"]["steps"]
    names = [str(step.get("name", "")) for step in steps if isinstance(step, dict)]
    sandbox_idx = next(i for i, name in enumerate(names) if name == "Build and push sandbox image")
    stamp_idx = next(
        i for i, name in enumerate(names) if name == "Stamp sandbox digest into gateway source"
    )
    gateway_idxs = [
        i
        for i, name in enumerate(names)
        if name
        in {
            "Build and push gateway image",
            "Build and push gateway browser image",
            "Build and push gateway GUI image",
        }
    ]
    assert stamp_idx > sandbox_idx, "stamp must run after sandbox build"
    assert gateway_idxs, "expected gateway image build steps"
    assert all(idx > stamp_idx for idx in gateway_idxs), (
        "stamp must run before every gateway image build"
    )
    stamp = steps[stamp_idx]
    assert "steps.sandbox.outputs.digest" in str(stamp.get("env", {}))
    run = str(stamp.get("run", ""))
    assert "stamp_default_sandbox_image.py" in run
    assert "--require-stamped" in run
    for idx in gateway_idxs:
        build_args = str(steps[idx].get("with", {}).get("build-args", ""))
        assert "SEVN_SANDBOX_IMAGE_DIGEST=${{ steps.sandbox.outputs.digest }}" in build_args
