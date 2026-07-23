from pathlib import Path
from tomllib import loads

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "requirements.lock"
PROJECT_PATH = ROOT / "pyproject.toml"


def locked_packages() -> dict[str, str]:
    packages: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        LOCK_PATH.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line or line.count("==") != 1:
            raise SystemExit(
                f"{LOCK_PATH.name}:{line_number}: dependency must use one exact == pin"
            )
        name, version = line.split("==", 1)
        canonical = canonicalize_name(name.strip())
        if not canonical or not version.strip():
            raise SystemExit(f"{LOCK_PATH.name}:{line_number}: invalid dependency pin")
        if canonical in packages:
            raise SystemExit(f"{LOCK_PATH.name}:{line_number}: duplicate package {canonical}")
        packages[canonical] = version.strip()
    if not packages:
        raise SystemExit("requirements.lock is empty")
    return packages


def declared_packages() -> set[str]:
    project = loads(PROJECT_PATH.read_text(encoding="utf-8"))["project"]
    declarations = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    declarations.extend(optional.get("dev", []))
    return {canonicalize_name(Requirement(value).name) for value in declarations}


def main() -> None:
    locked = locked_packages()
    missing = sorted(declared_packages() - locked.keys())
    if missing:
        raise SystemExit(
            "requirements.lock does not cover declared dependencies: " + ", ".join(missing)
        )
    print(f"requirements.lock contains {len(locked)} exact pins")


if __name__ == "__main__":
    main()
