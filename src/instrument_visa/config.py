from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SParameterConfig:
    format: str = "AUTO"
    s1: bool = False
    s2: bool = False
    s3: bool = False
    s4: bool = False

    @property
    def selected_ports(self) -> list[int]:
        return [
            port
            for port, enabled in enumerate((self.s1, self.s2, self.s3, self.s4), start=1)
            if enabled
        ]


@dataclass(frozen=True)
class AppConfig:
    address: str
    title: str = "Titel der Messung"
    timeout_ms: int = 10000
    output: Path = Path("results.xlsx")
    sparameters: SParameterConfig = SParameterConfig()


def load_config(path: Path) -> AppConfig:
    parser = ConfigParser()
    read_files = parser.read(path, encoding="utf-8")
    if not read_files:
        raise FileNotFoundError(f"Config file not found: {path}")

    address = parser.get("instrument", "address")
    title = parser.get("instrument", "title", fallback="Titel der Messung")
    timeout_ms = parser.getint("instrument", "timeout_ms", fallback=10000)
    output = Path(parser.get("export", "output", fallback="results.xlsx"))
    sparameters = SParameterConfig(
        format=parser.get("sparameters", "format", fallback="AUTO"),
        s1=parser.getboolean("sparameters", "s1", fallback=False),
        s2=parser.getboolean("sparameters", "s2", fallback=False),
        s3=parser.getboolean("sparameters", "s3", fallback=False),
        s4=parser.getboolean("sparameters", "s4", fallback=False),
    )

    return AppConfig(
        address=address,
        title=title,
        timeout_ms=timeout_ms,
        output=output,
        sparameters=sparameters,
    )
