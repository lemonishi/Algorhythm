"""The build metadata has to carry the non-Python assets.

`packages.find` only collects importable packages, so `editor/lua/` and
`runner/cpp/` are invisible to it. That goes unnoticed for as long as the
checkout is installed editable — and then a real `pip install .` produces a
build where `nvim_command` points `luafile` at nothing (no splits, no `:w`
hook, no `:Review`) and every C++ compile fails on a missing include.
"""

import tomllib
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "algorhythm"


def package_data() -> dict[str, list[str]]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return config["tool"]["setuptools"].get("package-data", {})


def shipped_assets() -> list[Path]:
    """Every non-Python file inside the package, ignoring build noise."""
    return sorted(
        path
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and path.suffix not in {".py", ".pyc"}
        and "__pycache__" not in path.parts
    )


def is_declared(path: Path, declarations: dict[str, list[str]]) -> bool:
    for package, patterns in declarations.items():
        package_dir = ROOT / Path(*package.split("."))
        if package_dir not in path.parents:
            continue
        relative = path.relative_to(package_dir).as_posix()
        if any(fnmatch(relative, pattern) for pattern in patterns):
            return True
    return False


def test_the_assets_we_know_about_are_present_in_the_tree():
    """Guards the test below from passing because the files moved."""
    assert (PACKAGE / "editor" / "lua" / "algorhythm.lua").exists()
    assert (PACKAGE / "runner" / "cpp" / "leetcode_types.h").exists()


def test_every_non_python_asset_is_declared_as_package_data():
    declarations = package_data()
    missing = [
        str(path.relative_to(ROOT))
        for path in shipped_assets()
        if not is_declared(path, declarations)
    ]
    assert missing == []
