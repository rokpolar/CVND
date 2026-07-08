import os
from pathlib import Path

import ee
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GEE_PROJECT_ID_ENV = "GEE_PROJECT_ID"


def get_gee_project_id() -> str:
    project_id = os.getenv(GEE_PROJECT_ID_ENV)
    if not project_id or not project_id.strip():
        raise RuntimeError(
            f"Missing {GEE_PROJECT_ID_ENV}.\n"
            "  1. cp .env.example .env\n"
            f"  2. Set {GEE_PROJECT_ID_ENV} in .env\n"
            "  3. Find your project ID at https://code.earthengine.google.com/"
        )
    return project_id.strip()


def initialize_gee() -> None:
    ee.Initialize(project=get_gee_project_id())
