from pathlib import Path
from typing import Iterable


def canonical_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def path_from(root: str | Path, *parts: str) -> Path:
    return canonical_path(Path(root).joinpath(*parts))


def output_path(root: str | Path, *parts: str) -> Path:
    return path_from(root, "output", *parts)


def ffconcat_path(path: str | Path) -> str:
    return canonical_path(path).as_posix().replace("'", "'\\''")


def require_directory(path: str | Path, label: str) -> Path:
    directory = Path(path)
    if not directory.is_dir():
        raise RuntimeError(f"{label} directory does not exist: {directory}")
    return directory


def require_file(path: str | Path, label: str) -> Path:
    file_path = Path(path)
    if not file_path.is_file():
        raise RuntimeError(f"{label} file does not exist: {file_path}")
    return file_path


def write_concat_file(path: str | Path, media_paths: Iterable[str | Path]) -> Path:
    concat_path = canonical_path(path)
    require_directory(concat_path.parent, "Concat output")
    with concat_path.open("w", encoding="utf-8") as concat_file:
        for media_path in media_paths:
            concat_file.write(f"file '{ffconcat_path(media_path)}'\n")
    return concat_path
