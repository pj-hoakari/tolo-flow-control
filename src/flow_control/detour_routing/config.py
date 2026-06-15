from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedConfig:
    k_shortest: int = 3
