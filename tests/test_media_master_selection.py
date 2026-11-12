"""An incomplete client catalog must not create a partially unlocked account."""
from types import SimpleNamespace
from unittest import mock

import pytest

from idoly_local import cli


@pytest.mark.parametrize("missing", ["master_tag", "asset_root", "asset_base_url", "master_dir"])
def test_cli_media_requires_a_complete_client_catalog_before_opening_state(missing, tmp_path):
    args = SimpleNamespace(media_mode=True, master_tag=tmp_path / "master-tag.json",
        asset_root=tmp_path / "assets", asset_base_url="http://127.0.0.1:8080",
        master_dir=tmp_path / "master-json")
    setattr(args, missing, None)
    with mock.patch.object(cli, "State", side_effect=AssertionError("opened account")):
        with pytest.raises(ValueError, match="--media-mode requires"):
            cli.serve(args, None)
