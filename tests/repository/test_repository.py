"""battery.repository standards against a FAKE in-memory GitHub - the transport is injected, so a whole
compliance run is rehearsed offline. An empty residual across the fleet proves every repo conforms."""
import io
import json
import unittest
import urllib.request
from http.client import HTTPMessage

from battery.repository import GitHub, RepoSetting, RepoTopic
from battery.repository._github import _SameOrigin, _Urllib

from cabaxiom import Reconciler


class _FakeHub:
    """A throwaway GitHub - a dict of repos, each with settings and a topic set, routed by URL path.
    It is the rehearsal world the transport carries requests into."""

    def __init__(self, repos: dict) -> None:
        self.repos = repos

    def transport(self, method, url, headers, body):
        parts = url.split("/repos/", 1)[1].split("/")
        repo = f"{parts[0]}/{parts[1]}"
        state = self.repos[repo]
        payload = json.loads(body) if body else None
        if len(parts) > 2 and parts[2] == "topics":
            if method == "PUT":
                state["topics"] = list(payload["names"])
            return 200, {"names": list(state["topics"])}
        if method == "PATCH":
            state["settings"].update(payload)
        return 200, dict(state["settings"])


def _hub(repos):
    fake = _FakeHub(repos)
    return GitHub("token", transport=fake.transport), fake


class RepoSettingTests(unittest.IsolatedAsyncioTestCase):
    def test_it_enforces_a_setting_and_is_idempotent(self):
        gh, fake = _hub({"acme/api": {"settings": {"has_issues": False}, "topics": []}})
        step = RepoSetting(gh, "acme/api", "has_issues", True)
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["has_issues is False, want True"])
        self.assertEqual([d.message for d in step.apply({})[0]], ["has_issues set to True"])
        self.assertTrue(fake.repos["acme/api"]["settings"]["has_issues"])
        self.assertEqual(step.assess({})[0].deviation, [])
        self.assertIsNone(step.apply({})[0])                     # idempotent

    def test_a_conforming_setting_shows_no_drift(self):
        gh, _ = _hub({"acme/api": {"settings": {"default_branch": "main"}, "topics": []}})
        self.assertEqual(RepoSetting(gh, "acme/api", "default_branch", "main").assess({})[0].deviation, [])


class RepoTopicTests(unittest.IsolatedAsyncioTestCase):
    def test_it_adds_a_topic_and_reverses_it(self):
        gh, fake = _hub({"acme/api": {"settings": {}, "topics": ["python"]}})
        step = RepoTopic(gh, "acme/api", "reconciliation")
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["topic 'reconciliation' missing"])
        self.assertEqual([d.message for d in step.apply({})[0]], ["topic 'reconciliation' added"])
        self.assertIn("reconciliation", fake.repos["acme/api"]["topics"])
        self.assertIsNone(step.apply({})[0])                     # idempotent
        self.assertEqual([d.message for d in step.assess({})[0].footprint], ["topic 'reconciliation' present"])
        self.assertEqual(step.prune({})[0], [])
        self.assertNotIn("reconciliation", fake.repos["acme/api"]["topics"])
        self.assertEqual(step.prune({})[0], [])                  # already gone, clean
        self.assertEqual(step.assess({})[0].footprint, [])


class FleetComplianceTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_residual_is_a_compliance_report_then_a_proof(self):
        gh, fake = _hub({
            "acme/api": {"settings": {"has_issues": True}, "topics": []},
            "acme/web": {"settings": {"has_issues": False}, "topics": []},   # the non-conforming one
            "acme/cli": {"settings": {"has_issues": True}, "topics": []},
        })
        standard = [RepoSetting(gh, repo, "has_issues", True) for repo in fake.repos]

        # A read-only compliance check names exactly the repo that does not conform.
        report = await Reconciler(standard).assess()
        self.assertEqual([d.name for d in report], ["acme/web"])

        # Converge enforces it. The empty residual PROVES the whole fleet now conforms.
        residual = await Reconciler(standard).converge()
        self.assertEqual(residual, [])
        self.assertTrue(fake.repos["acme/web"]["settings"]["has_issues"])
        # And a second pass changes nothing - the standard holds.
        second = await Reconciler(standard).converge()
        self.assertEqual([item.message for item in second.applied], [])


class DefaultTransportTests(unittest.IsolatedAsyncioTestCase):
    """A session built without an injected transport wires the real one, with the timeout that keeps a
    silent peer from holding the calling thread and the opener that keeps the token on its origin."""

    def test_it_carries_the_timeout_and_the_same_origin_rule(self):
        session = GitHub("token", timeout=2.5)
        carried = session._transport
        self.assertIsInstance(carried, _Urllib)
        self.assertEqual(carried._timeout, 2.5)
        self.assertTrue(any(isinstance(handler, _SameOrigin) for handler in carried._opener.handlers))

    def test_an_injected_transport_wins(self):
        def fake(method, url, headers, body):
            return 200, {}

        self.assertIs(GitHub("token", transport=fake)._transport, fake)


class SameOriginRedirectTests(unittest.IsolatedAsyncioTestCase):
    """The token must not leave the origin it was minted for. urllib copies every header onto a
    redirected request with no origin check, so the session's opener carries this rule instead."""

    def _redirect(self, target: str):
        request = urllib.request.Request(
            "https://api.github.com/repos/acme/api",
            headers={"Authorization": "Bearer ghp_SECRET", "Accept": "application/vnd.github+json"},
        )
        handler = _SameOrigin()
        return handler.redirect_request(request, io.BytesIO(), 302, "Found", HTTPMessage(), target)

    def test_a_cross_origin_redirect_loses_the_authorization_header(self):
        redirected = self._redirect("https://elsewhere.example/steal")
        self.assertNotIn("Authorization", redirected.headers)
        self.assertIn("Accept", redirected.headers)          # only the credential is stripped

    def test_a_same_origin_redirect_keeps_it(self):
        redirected = self._redirect("https://api.github.com/repositories/1")
        self.assertEqual(redirected.headers["Authorization"], "Bearer ghp_SECRET")

    def test_a_scheme_downgrade_counts_as_another_origin(self):
        redirected = self._redirect("http://api.github.com/repos/acme/api")
        self.assertNotIn("Authorization", redirected.headers)

    def test_a_foreign_scheme_on_the_same_host_is_still_another_origin(self):
        redirected = self._redirect("ftp://api.github.com/repos/acme/api")
        self.assertNotIn("Authorization", redirected.headers)


class BareStandardTests(unittest.IsolatedAsyncioTestCase):
    """The bridge's defaults are the contract a domain's own standard builds on. Override only the
    judgements you own, where the rest stays quiet instead of inventing findings."""

    async def test_a_standard_that_overrides_nothing_is_quiet_on_every_channel(self):
        from battery.repository.standards import _Standard

        class Inert(_Standard):
            pass

        reconciler = Reconciler((Inert(),))
        self.assertEqual(await reconciler.converge(), [])
        self.assertEqual(await reconciler.prune(), [])
