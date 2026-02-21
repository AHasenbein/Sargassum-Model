from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sargassum_model.config import load_config
from src.sargassum_model.pyrolysis_model import run_pyrolysis
from src.sargassum_model.run_model import run_pipeline
from src.sargassum_model.validation import validate_and_normalize_config


def main() -> None:
    cfg = validate_and_normalize_config(load_config("config/model_config.yaml"))
    run_pipeline("config/model_config.yaml", "outputs")
    run_pyrolysis(cfg)
    print("smoke_test: ok")


if __name__ == "__main__":
    main()
