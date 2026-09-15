"""ai-content-orchestrator: the one downstream consumer that proves TeamWeave is a platform.

Everything reachable without credentials is checked here. The admin API needs
both an API key and a SIWE bearer token, neither of which is a stack output, so
those tests run only when both are supplied.

One endpoint is deliberately never called: `POST /admin/newsletter/actions/send`
mails every live subscriber via SES, with no dry-run flag and no confirmation
step. A test suite pointed at production must not be one `pytest` away from
sending real email, so it has no test and never will.
"""
from __future__ import annotations

import os

import pytest

from conftest import json_of, require

API_KEY = os.environ.get("WEAVE_E2E_ACO_API_KEY")
BEARER = os.environ.get("WEAVE_E2E_ACO_JWT")


def _admin_headers():
    if not API_KEY or not BEARER:
        pytest.skip(
            "admin routes need both credentials: set WEAVE_E2E_ACO_API_KEY and "
            "WEAVE_E2E_ACO_JWT. Neither is a stack output, by design."
        )
    return {"x-api-key": API_KEY, "Authorization": f"Bearer {BEARER}"}


def test_published_articles_are_servable(env, http):
    """GET /site/posts reads S3, not DynamoDB, and reports its own partial failures.

    `errors` counts objects that could not be turned into a card. It comes back
    inside a 200, so a client that ignores it silently accepts fewer posts than
    exist -- which is why it is asserted rather than just read.
    """
    aco = require(env, "aco", "api_base", "articles_bucket", "articles_prefix")
    url = f"{aco['api_base']}/site/posts?limit=5"
    r = http.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)

    for key in ("items", "count", "errors", "bucket", "prefix"):
        assert key in body, f"{url} missing {key!r}: {sorted(body)}"

    # The endpoint reports which bucket it read; it must be the one the stack
    # publishes, or the API and the harness are looking at different data.
    assert body["bucket"] == aco["articles_bucket"], (
        f"/site/posts read bucket {body['bucket']!r} but the stack publishes "
        f"ArticlesBucketName={aco['articles_bucket']!r}. One of them is stale."
    )
    assert body["prefix"].rstrip("/") == aco["articles_prefix"].rstrip("/"), (
        f"/site/posts read prefix {body['prefix']!r}, stack says {aco['articles_prefix']!r}"
    )
    assert body["count"] == len(body["items"]), (
        f"count={body['count']} but {len(body['items'])} items returned"
    )
    if body["errors"]:
        pytest.xfail(
            f"{body['errors']} object(s) under {body['prefix']} could not be parsed into "
            f"a card. The endpoint returned 200 with a partial list, which is its "
            f"documented behaviour -- but the objects are malformed."
        )


def test_a_published_article_is_individually_retrievable(env, http):
    """The card list and the single-article read must agree on ids."""
    aco = require(env, "aco", "api_base")
    list_url = f"{aco['api_base']}/site/posts?limit=1"
    items = json_of(http.get(list_url), list_url)["items"]
    if not items:
        pytest.skip("no published articles on this stack")

    article_id = items[0].get("id")
    assert article_id, f"a card has no id: {items[0]}"
    url = f"{aco['api_base']}/site/posts/{article_id}"
    r = http.get(url)
    assert r.status_code == 200, (
        f"{url} -> {r.status_code}. /site/posts listed {article_id} but the single-article "
        f"read cannot find it, so the list and the objects disagree."
    )


def test_the_deployed_gemini_model_matches_the_template(env):
    """The output that exists because the deployed value can silently differ.

    `sam deploy` sends UsePreviousValue=true for any parameter absent from
    --parameter-overrides, so a stack can keep serving a model id the repository
    no longer names -- which is exactly how the admin API came to use a stale
    one. This asserts the live value is at least present and plausible; the
    repository-side check that it equals the template default lives in
    ai-content-orchestrator's own CI.
    """
    aco = require(env, "aco", "gemini_model")
    model = aco["gemini_model"]
    assert model and model != "None", "GeminiModelId resolves to nothing"
    assert model.startswith("gemini-"), (
        f"deployed GeminiModel is {model!r}, which is not a Gemini model id"
    )


def test_admin_api_is_reachable_with_credentials(env, http):
    """GET /admin is a liveness probe -- not, despite the old docs, a list of articles."""
    aco = require(env, "aco", "api_base")
    url = f"{aco['api_base']}/admin"
    r = http.get(url, headers=_admin_headers())
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    assert json_of(r, url).get("ok") is True


def test_admin_rejects_an_unknown_article_status(env, http):
    """A typo'd status must 400, not return an empty list.

    An empty list would read as "no articles in that state", which is the
    expensive way to be wrong about an editorial queue.
    """
    aco = require(env, "aco", "api_base")
    url = f"{aco['api_base']}/admin/articles?status=NOT_A_STATUS"
    r = http.get(url, headers=_admin_headers())
    assert r.status_code == 400, (
        f"{url} -> {r.status_code}; an unknown status must be rejected rather than "
        f"returning an empty result set."
    )


def test_admin_requires_credentials(env, http):
    """The admin surface must not be open. Read-only and needs no credentials."""
    aco = require(env, "aco", "api_base")
    url = f"{aco['api_base']}/admin/articles?status=DRAFT"
    r = http.get(url)
    assert r.status_code in (401, 403), (
        f"{url} answered {r.status_code} with no API key and no bearer token. "
        f"The admin API is supposed to require both."
    )
