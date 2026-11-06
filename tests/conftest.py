import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

# Captured with: query="data analyst", postal_code=83702, radius=25.
# Chosen as a neutral, generic sample: 38 results, single page.
FIXTURE_NAME = "classic_83702_data_analyst.json"


@pytest.fixture(scope="session")
def payload() -> dict:
    """Real captured response from /_next/data/<buildId>/classic.json."""
    return json.loads((FIXTURES / FIXTURE_NAME).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def page_props(payload) -> dict:
    return payload["pageProps"]


@pytest.fixture(scope="session")
def upstream_search_state(page_props) -> dict:
    """The exact searchState the live site echoed back."""
    return page_props["initialSearchState"]
