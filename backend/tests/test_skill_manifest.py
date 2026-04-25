import textwrap
from pathlib import Path

from deerflow.skills.manifest import load_skill_manifest


def test_load_full_manifest(tmp_path: Path):
    skill_dir = tmp_path / "data-analyst"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(textwrap.dedent("""\
        name: data-analyst
        version: 1.2.0
        scope: org
        description: 数据分析专家技能
        requires_tools:
          - code_execution
          - web_search
        requires_mcp:
          - postgres-mcp
        env:
          - name: ORG_ACCESS_KEY
            source: org_key
            required: true
        changelog: "增加 SQL 优化建议"
    """))

    manifest = load_skill_manifest(skill_dir)

    assert manifest is not None
    assert manifest.name == "data-analyst"
    assert manifest.version == "1.2.0"
    assert manifest.scope == "org"
    assert manifest.requires_tools == ["code_execution", "web_search"]
    assert manifest.requires_mcp == ["postgres-mcp"]
    assert len(manifest.env) == 1
    assert manifest.env[0].name == "ORG_ACCESS_KEY"
    assert manifest.env[0].source == "org_key"
    assert manifest.env[0].required is True


def test_load_minimal_manifest(tmp_path: Path):
    skill_dir = tmp_path / "simple"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text("name: simple\nversion: 1.0.0\n")

    manifest = load_skill_manifest(skill_dir)

    assert manifest is not None
    assert manifest.name == "simple"
    assert manifest.version == "1.0.0"
    assert manifest.requires_tools == []
    assert manifest.requires_mcp == []
    assert manifest.env == []


def test_load_manifest_missing_returns_none(tmp_path: Path):
    skill_dir = tmp_path / "no-manifest"
    skill_dir.mkdir()

    manifest = load_skill_manifest(skill_dir)
    assert manifest is None


def test_load_manifest_invalid_yaml(tmp_path: Path):
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text("name: [invalid\n")

    manifest = load_skill_manifest(skill_dir)
    assert manifest is None


def test_parse_skill_spec_with_version():
    from deerflow.skills.manifest import parse_skill_spec
    assert parse_skill_spec("data-analyst@v1.2.0") == ("data-analyst", "1.2.0")
    assert parse_skill_spec("data-analyst@1.2.0") == ("data-analyst", "1.2.0")
    assert parse_skill_spec("data-analyst") == ("data-analyst", None)
    assert parse_skill_spec("sql-expert@v2") == ("sql-expert", "2")
