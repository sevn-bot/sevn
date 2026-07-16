"""Platform medium resolution, capabilities matrix, and browser-plan contracts (W1.0-W1.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sevn.browser.recipes.social import _SUPPORTED_SITES

_EXPECTED_SITES = frozenset({"x", "facebook", "instagram", "linkedin", "reddit", "tiktok"})


def _import_medium_module() -> Any:
    from sevn.integrations.social_media import medium as mod

    return mod


def _import_worker_module() -> Any:
    from sevn.agent.subagents import social_media_worker as mod

    return mod


def _skills_block(
    *,
    default_medium: str = "browser",
    platform_media: dict[str, str] | None = None,
) -> dict[str, Any]:
    platforms: dict[str, Any] = {}
    for site, medium in (platform_media or {}).items():
        platforms[site] = {"medium": medium}
    return {
        "default_medium": default_medium,
        "twexapi": {"enabled": False},
        "platforms": platforms,
    }


class TestSiteSsot:
    """D6 — platform keys match ``social.py`` SSOT (runs on pre-0.0.1)."""

    def test_supported_sites_match_inventory(self) -> None:
        assert _SUPPORTED_SITES == _EXPECTED_SITES

    def test_supported_sites_count(self) -> None:
        assert len(_SUPPORTED_SITES) == 6


class TestResolveSocialMedium:
    """W1.0 — resolution order: task → platform → default_medium → browser (D2)."""

    @pytest.mark.parametrize(
        ("task_medium", "platform_medium", "default_medium", "site", "expected"),
        [
            ("twexapi", "browser", "browser", "x", "twexapi"),
            (None, "twexapi", "browser", "x", "twexapi"),
            (None, "browser", "twexapi", "x", "browser"),
            (None, None, "twexapi", "x", "twexapi"),
            (None, None, None, "x", "browser"),
            ("twexapi", "twexapi", "twexapi", "facebook", "browser"),
            (None, "twexapi", "twexapi", "linkedin", "browser"),
        ],
    )
    def test_resolution_order(
        self,
        task_medium: str | None,
        platform_medium: str | None,
        default_medium: str | None,
        site: str,
        expected: str,
    ) -> None:
        medium_mod = _import_medium_module()
        cfg = _skills_block(
            default_medium=default_medium or "browser",
            platform_media={site: platform_medium} if platform_medium else {},
        )
        task: dict[str, Any] = {"site": site}
        if task_medium is not None:
            task["medium"] = task_medium
        assert medium_mod.resolve_social_medium(task, cfg, site) == expected

    def test_unknown_site_rejected(self) -> None:
        medium_mod = _import_medium_module()
        with pytest.raises(ValueError, match=r"unknown|unsupported|site"):
            medium_mod.resolve_social_medium({}, _skills_block(), "mastodon")

    def test_twexapi_non_x_coerces_to_browser(self) -> None:
        medium_mod = _import_medium_module()
        cfg = _skills_block(default_medium="twexapi", platform_media={"facebook": "twexapi"})
        assert medium_mod.resolve_social_medium({}, cfg, "facebook") == "browser"


class TestAllowedMediaForSite:
    """W1.1 — allowed_media per site; twexapi only on x (D3/D4)."""

    @pytest.mark.parametrize(
        ("site", "expected"),
        [
            ("x", ("browser", "twexapi")),
            ("facebook", ("browser",)),
            ("instagram", ("browser",)),
            ("linkedin", ("browser",)),
            ("reddit", ("browser",)),
            ("tiktok", ("browser",)),
        ],
    )
    def test_allowed_media(self, site: str, expected: tuple[str, ...]) -> None:
        medium_mod = _import_medium_module()
        assert medium_mod.allowed_media_for_site(site) == expected

    def test_unknown_site_rejected(self) -> None:
        medium_mod = _import_medium_module()
        with pytest.raises(ValueError, match=r"unknown|unsupported|site"):
            medium_mod.allowed_media_for_site("threads")


def _smm_cfg_json() -> dict[str, Any]:
    return {
        "specialists": {
            "social_media_manager": {
                "model": "gpt-4o-mini",
                "provider": "openai",
                "assigned_to": ["tier_b"],
                "requestable_by": ["triager", "tier_b"],
                "max_concurrent": 2,
                "skill": "social_media_manager",
            },
        },
    }


class TestCapabilitiesMatrix:
    """W1.1 — per-platform capabilities payload (D7/D8)."""

    @pytest.fixture
    def smm_workspace(self, tmp_path: Path) -> Path:
        root = tmp_path / "ws"
        root.mkdir()
        (root / "sevn.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "gateway": {"token": "test-token"},
                    "skills": {
                        "social_media_manager": {
                            "default_medium": "browser",
                            "platforms": {"x": {"medium": "twexapi"}},
                            "twexapi": {"enabled": True, "api_key": "sk-test"},
                        },
                    },
                    "subagents": _smm_cfg_json(),
                },
            ),
            encoding="utf-8",
        )
        return root

    @pytest.mark.asyncio
    async def test_all_six_sites_present(self, smm_workspace: Path) -> None:
        worker = _import_worker_module()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        cfg = SubAgentsWorkspaceConfig.model_validate(_smm_cfg_json())
        result = await worker.execute_social_media_manager_task(
            '{"medium":"capabilities"}',
            content_root=smm_workspace,
            subagents_cfg=cfg,
        )
        matrix = result.get("platforms") or result.get("matrix") or result
        assert isinstance(matrix, dict)
        for site in _SUPPORTED_SITES:
            assert site in matrix

    @pytest.mark.asyncio
    async def test_each_site_allows_browser(self, smm_workspace: Path) -> None:
        worker = _import_worker_module()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        cfg = SubAgentsWorkspaceConfig.model_validate(_smm_cfg_json())
        result = await worker.execute_social_media_manager_task(
            '{"medium":"capabilities"}',
            content_root=smm_workspace,
            subagents_cfg=cfg,
        )
        matrix = result["platforms"]
        for site in _SUPPORTED_SITES:
            entry = matrix[site]
            assert "browser" in entry["allowed_media"]

    @pytest.mark.asyncio
    async def test_only_x_allows_twexapi(self, smm_workspace: Path) -> None:
        worker = _import_worker_module()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        cfg = SubAgentsWorkspaceConfig.model_validate(_smm_cfg_json())
        result = await worker.execute_social_media_manager_task(
            '{"medium":"capabilities"}',
            content_root=smm_workspace,
            subagents_cfg=cfg,
        )
        matrix = result["platforms"]
        assert "twexapi" in matrix["x"]["allowed_media"]
        for site in _SUPPORTED_SITES - {"x"}:
            assert "twexapi" not in matrix[site]["allowed_media"]

    @pytest.mark.asyncio
    async def test_effective_medium_from_platform_default(self, smm_workspace: Path) -> None:
        worker = _import_worker_module()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        cfg = SubAgentsWorkspaceConfig.model_validate(_smm_cfg_json())
        result = await worker.execute_social_media_manager_task(
            '{"medium":"capabilities"}',
            content_root=smm_workspace,
            subagents_cfg=cfg,
        )
        assert result["platforms"]["x"]["effective_medium"] == "twexapi"
        assert result["platforms"]["facebook"]["effective_medium"] == "browser"

    @pytest.mark.parametrize(
        ("site", "must_include", "must_exclude"),
        [
            ("x", ("social_media_manager",), ("browser-harness",)),
            ("facebook", ("social_media_manager",), ("browser-harness",)),
            ("linkedin", ("social_media_manager",), ("yt-dlp",)),
            ("instagram", ("browser-harness",), ("last30days",)),
            ("reddit", ("browser-harness", "last30days"), ("yt-dlp",)),
            ("tiktok", ("browser-harness", "yt-dlp"), ("last30days",)),
        ],
    )
    @pytest.mark.asyncio
    async def test_site_appropriate_skills(
        self,
        smm_workspace: Path,
        site: str,
        must_include: tuple[str, ...],
        must_exclude: tuple[str, ...],
    ) -> None:
        worker = _import_worker_module()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        cfg = SubAgentsWorkspaceConfig.model_validate(_smm_cfg_json())
        result = await worker.execute_social_media_manager_task(
            '{"medium":"capabilities"}',
            content_root=smm_workspace,
            subagents_cfg=cfg,
        )
        skills = result["platforms"][site]["skills"]
        for skill in must_include:
            assert skill in skills
        for skill in must_exclude:
            assert skill not in skills


class TestTwexApiXOnlyGuard:
    """W1.2 — twexapi path never calls HTTP for non-x sites (D3)."""

    @pytest.fixture
    def smm_workspace(self, tmp_path: Path) -> Path:
        root = tmp_path / "ws"
        root.mkdir()
        (root / "sevn.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "gateway": {"token": "test-token"},
                    "skills": {
                        "social_media_manager": {
                            "default_medium": "twexapi",
                            "twexapi": {"enabled": True, "api_key": "sk-test"},
                        },
                    },
                    "subagents": {
                        "specialists": {
                            "social_media_manager": {
                                "model": "gpt-4o-mini",
                                "provider": "openai",
                                "skill": "social_media_manager",
                                "tools": ["browser"],
                            },
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        return root

    @pytest.mark.asyncio
    async def test_linkedin_twexapi_task_never_calls_client(self, smm_workspace: Path) -> None:
        worker = _import_worker_module()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        raw = json.loads(smm_workspace.joinpath("sevn.json").read_text(encoding="utf-8"))
        cfg = SubAgentsWorkspaceConfig.model_validate(raw["subagents"])
        call_mock = AsyncMock(return_value={"tweets": []})
        with patch.object(worker.TwexApiClient, "call_op", call_mock):
            result = await worker.execute_social_media_manager_task(
                '{"medium":"twexapi","op":"search","site":"linkedin","query":"ai"}',
                content_root=smm_workspace,
                subagents_cfg=cfg,
            )
        call_mock.assert_not_called()
        assert result["medium"] == "browser"
        assert result.get("tool") == "browser"

    @pytest.mark.asyncio
    async def test_facebook_task_medium_twexapi_coerces(self, smm_workspace: Path) -> None:
        worker = _import_worker_module()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        raw = json.loads(smm_workspace.joinpath("sevn.json").read_text(encoding="utf-8"))
        cfg = SubAgentsWorkspaceConfig.model_validate(raw["subagents"])
        call_mock = AsyncMock()
        with patch.object(worker.TwexApiClient, "call_op", call_mock):
            result = await worker.execute_social_media_manager_task(
                '{"medium":"twexapi","op":"search","site":"facebook","query":"x"}',
                content_root=smm_workspace,
                subagents_cfg=cfg,
            )
        call_mock.assert_not_called()
        assert result["medium"] == "browser"


class TestBrowserPlanSkills:
    """W1.3 — browser plan lists site-appropriate skills (D7)."""

    @pytest.mark.parametrize(
        ("site", "must_include", "must_exclude"),
        [
            ("instagram", ("browser-harness",), ("last30days",)),
            ("x", ("social_media_manager",), ()),
            ("facebook", ("social_media_manager",), ("yt-dlp",)),
            ("tiktok", ("browser-harness", "yt-dlp"), ("last30days",)),
        ],
    )
    def test_browser_plan_skill_hints(
        self,
        site: str,
        must_include: tuple[str, ...],
        must_exclude: tuple[str, ...],
    ) -> None:
        worker = _import_worker_module()
        task = worker.SocialMediaTask(
            medium="browser",
            op="search",
            params={},
            body={},
            path_params={},
            site=site,
            query="test",
        )
        plan = worker._browser_plan(task)
        skills = plan["skills"]
        for skill in must_include:
            assert skill in skills
        for skill in must_exclude:
            assert skill not in skills

    def test_browser_plan_cdp_fields(self) -> None:
        worker = _import_worker_module()
        task = worker.SocialMediaTask(
            medium="browser",
            op="search",
            params={},
            body={},
            path_params={},
            site="instagram",
            query="bots",
        )
        plan = worker._browser_plan(task)
        assert plan["tool"] == "browser"
        assert plan["action"] == "social"
        assert plan["site"] == "instagram"
        assert plan["engine"] == "cdp"
