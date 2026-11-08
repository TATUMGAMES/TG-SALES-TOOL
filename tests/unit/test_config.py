from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tg_sales import config
from tg_sales.config import DATA_DIR_ENV_VAR, AppPaths
from tg_sales.errors import DataDirectoryError


def test_default_root_is_per_user_local_app_data() -> None:
    paths = AppPaths.resolve(environ={})
    assert paths.custom is False
    assert paths.root == config.default_data_root()
    assert paths.root.parts[-2:] == ("TatumGames", "tg_sales")
    if sys.platform == "win32":
        assert "Roaming" not in paths.root.parts


def test_environment_variable_selects_custom_root(data_root: Path) -> None:
    paths = AppPaths.resolve(environ={DATA_DIR_ENV_VAR: str(data_root)})
    assert paths.custom is True
    assert paths.root == data_root.resolve()


def test_cli_option_overrides_environment(tmp_path: Path, data_root: Path) -> None:
    other = tmp_path / "other"
    paths = AppPaths.resolve(str(data_root), environ={DATA_DIR_ENV_VAR: str(other)})
    assert paths.root == data_root.resolve()


def test_blank_environment_value_uses_default() -> None:
    paths = AppPaths.resolve(environ={DATA_DIR_ENV_VAR: "   "})
    assert paths.custom is False


def test_relative_custom_root_is_rejected() -> None:
    with pytest.raises(DataDirectoryError) as info:
        AppPaths.resolve("relative\\folder", environ={})
    assert "full path" in info.value.user_message
    assert info.value.suggested_action


def test_custom_root_inside_install_dir_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "tg_sales_windows_x64"
    install.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "tg_sales.exe"))
    with pytest.raises(DataDirectoryError) as info:
        AppPaths.resolve(str(install / "data"), environ={})
    assert "program folder" in info.value.user_message


def test_custom_root_outside_install_dir_is_allowed_when_frozen(
    tmp_path: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "app"
    install.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "tg_sales.exe"))
    assert config.install_dir() == install.resolve()
    assert AppPaths.resolve(str(data_root), environ={}).root == data_root.resolve()


def test_install_dir_is_none_from_source() -> None:
    assert config.is_frozen() is False
    assert config.install_dir() is None


def test_ensure_creates_all_directories_with_unicode_path(data_root: Path) -> None:
    paths = AppPaths(root=data_root, custom=True)
    paths.ensure()
    for directory in paths.all_dirs():
        assert directory.is_dir()
        assert directory.parent == data_root
    assert paths.database_file == data_root / "data" / "tg_sales.db"
    assert not (data_root / ".write_test").exists()


def test_ensure_is_idempotent(data_root: Path) -> None:
    paths = AppPaths(root=data_root)
    paths.ensure()
    paths.ensure()


def test_ensure_reports_unwritable_location(tmp_path: Path) -> None:
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(DataDirectoryError) as info:
        AppPaths(root=blocker).ensure()
    assert str(blocker) in info.value.user_message
    assert "permission" in info.value.suggested_action
    assert info.value.detail


def test_all_dirs_are_distinct() -> None:
    dirs = AppPaths(root=Path("C:/x")).all_dirs()
    assert len(set(dirs)) == len(dirs)


def test_resource_path_points_into_package() -> None:
    path = config.resource_path("icons", "app.png")
    assert path.parts[-3:] == ("resources", "icons", "app.png")
    assert path.parent.parent.is_dir()
