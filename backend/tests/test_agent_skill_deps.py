from unittest.mock import patch

from deerflow.config.agents_config import AgentConfig
from deerflow.skills.manifest import EnvDeclaration, SkillManifest


def _make_manifest(requires_tools=None, requires_mcp=None, env=None):
    return SkillManifest(
        name="test-skill",
        version="1.0.0",
        requires_tools=requires_tools or [],
        requires_mcp=requires_mcp or [],
        env=env or [],
    )


def test_agent_config_accepts_org_key_env():
    cfg = AgentConfig(
        name="sales-agent",
        skills=["data-analyst@v2.0.0", "sql-expert"],
        org_key_env="ORG_ACCESS_KEY",
    )
    assert cfg.org_key_env == "ORG_ACCESS_KEY"
    assert cfg.skills == ["data-analyst@v2.0.0", "sql-expert"]


def test_agent_config_org_key_env_defaults_none():
    cfg = AgentConfig(name="default-agent")
    assert cfg.org_key_env is None


def test_resolve_skills_and_deps_merges_tool_groups(tmp_path):
    from deerflow.agents.lead_agent.agent import _resolve_skills_and_deps

    cfg = AgentConfig(
        name="my-agent",
        skills=["skill-a", "skill-b"],
    )
    manifests = {
        "skill-a": _make_manifest(requires_tools=["code_execution"]),
        "skill-b": _make_manifest(requires_tools=["web_search", "code_execution"]),
    }

    with patch("deerflow.agents.lead_agent.agent.load_skill_manifest_by_name",
               side_effect=lambda name, version: manifests.get(name)):
        skill_names, extra_tools, env_injections = _resolve_skills_and_deps(cfg)

    assert skill_names == {"skill-a", "skill-b"}
    assert set(extra_tools) == {"code_execution", "web_search"}
    assert env_injections == {}


def test_resolve_skills_and_deps_injects_org_key(monkeypatch):
    from deerflow.agents.lead_agent.agent import _resolve_skills_and_deps

    monkeypatch.setenv("MY_ORG_KEY", "sk_org_testvalue")

    cfg = AgentConfig(
        name="sales-agent",
        skills=["data-analyst"],
        org_key_env="MY_ORG_KEY",
    )
    manifest = _make_manifest(
        env=[EnvDeclaration(name="ORG_ACCESS_KEY", source="org_key", required=True)]
    )

    with patch("deerflow.agents.lead_agent.agent.load_skill_manifest_by_name",
               return_value=manifest):
        _, _, env_injections = _resolve_skills_and_deps(cfg)

    assert env_injections == {"ORG_ACCESS_KEY": "sk_org_testvalue"}


def test_resolve_skills_and_deps_no_skills_returns_empty():
    from deerflow.agents.lead_agent.agent import _resolve_skills_and_deps

    cfg = AgentConfig(name="plain-agent")
    skill_names, extra_tools, env_injections = _resolve_skills_and_deps(cfg)

    assert skill_names == set()
    assert extra_tools == []
    assert env_injections == {}
