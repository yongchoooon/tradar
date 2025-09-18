"""Image utilities placeholder."""


def load_image(path: str) -> bytes:  # pragma: no cover
    with open(path, "rb") as fh:
        return fh.read()
