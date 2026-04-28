"""Tests for the lifted _extract_scope helper.

Covers the four cases that uploads.py and artifacts.py currently exercise
indirectly: identity-flag-off, anonymous, valid full ids, and invalid/partial ids.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.gateway.identity.request_scope import extract_scope


def _request(*, identity=None) -> MagicMock:
    req = MagicMock()
    req.state = SimpleNamespace(identity=identity)
    return req


@patch("app.gateway.identity.request_scope.get_identity_settings")
class TestExtractScope:
    def test_returns_none_pair_when_request_is_none(self, mock_settings):
        mock_settings.return_value.enabled = True
        assert extract_scope(None) == (None, None)

    def test_returns_none_pair_when_flag_off(self, mock_settings):
        mock_settings.return_value.enabled = False
        identity = SimpleNamespace(tenant_id=5, workspace_id=7)
        assert extract_scope(_request(identity=identity)) == (None, None)

    def test_returns_none_pair_when_anonymous(self, mock_settings):
        mock_settings.return_value.enabled = True
        identity = SimpleNamespace(tenant_id=5, workspace_id=7, is_authenticated=False)
        assert extract_scope(_request(identity=identity)) == (None, None)

    def test_returns_full_pair_when_authenticated(self, mock_settings):
        mock_settings.return_value.enabled = True
        identity = SimpleNamespace(tenant_id=5, workspace_id=7, is_authenticated=True)
        assert extract_scope(_request(identity=identity)) == (5, 7)

    def test_falls_back_to_first_workspace_id(self, mock_settings):
        mock_settings.return_value.enabled = True
        identity = SimpleNamespace(
            tenant_id=5, workspace_id=None, workspace_ids=[7, 9], is_authenticated=True
        )
        assert extract_scope(_request(identity=identity)) == (5, 7)

    def test_returns_none_pair_when_either_id_invalid(self, mock_settings):
        mock_settings.return_value.enabled = True
        for tenant_id, workspace_id in [(0, 7), (-1, 7), (5, 0), (5, -1), (True, 7), (5, False)]:
            identity = SimpleNamespace(
                tenant_id=tenant_id, workspace_id=workspace_id, is_authenticated=True
            )
            assert extract_scope(_request(identity=identity)) == (None, None), (
                f"failed for ({tenant_id!r}, {workspace_id!r})"
            )

    def test_returns_none_pair_when_identity_absent(self, mock_settings):
        mock_settings.return_value.enabled = True
        assert extract_scope(_request(identity=None)) == (None, None)
