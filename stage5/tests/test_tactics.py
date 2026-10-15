from pathlib import Path
from types import SimpleNamespace
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tactics import Tactician


def state():
    return dict(mission='follow', observed=dict(target_candidates=[], target_response_source='http',
                local_space=dict(motion_candidates={'forward_1m': {'status': 'unknown'},
                    'forward_left_1m': {'status': 'unknown'}})))


class FakeClient:
    def __init__(self, maneuver='brake', fail_once=False, delay=0):
        self.maneuver, self.fail_once, self.delay, self.calls = maneuver, fail_once, delay, 0

    def system_one(self, **kwargs):
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RuntimeError('test failure')
        time.sleep(self.delay)
        return SimpleNamespace(answers={'maneuver': SimpleNamespace(choice=self.maneuver, confidence=.8,
            probabilities={self.maneuver: 1}), 'risk': SimpleNamespace(score=1),
            'target_ambiguous': SimpleNamespace(noul=.8)},
            usage=SimpleNamespace(input_tokens=None, output_tokens=None))

    def close(self):
        pass


class TacticsTests(unittest.TestCase):
    def actor(self, client, budget=2, ttl=1.5):
        actor = Tactician({'JEV_CALL_HZ':'1000', 'JEV_CALL_BUDGET':str(budget),
                          'JEV_TIMEOUT':'1', 'JEV_RETRY_BASE_S':'.1', 'JEV_STALE_AFTER_S':str(ttl)}, client=client)
        self.addCleanup(actor.close)
        return actor

    def test_budget_and_cache(self):
        actor = self.actor(FakeClient(), budget=1)
        self.assertTrue(actor.offer(state(), time.monotonic()))
        self.assertEqual(actor.wait_result()['source'], 'jev')
        self.assertFalse(actor.offer(state(), time.monotonic()))
        self.assertEqual(actor.stats()['attempts'], 1)

    def test_failure_can_retry_same_scene(self):
        actor = self.actor(FakeClient(fail_once=True))
        self.assertTrue(actor.offer(state(), time.monotonic()))
        self.assertEqual(actor.wait_result()['source'], 'error')
        time.sleep(.12)
        self.assertTrue(actor.offer(state(), time.monotonic()))
        self.assertEqual(actor.wait_result()['source'], 'jev')

    def test_late_answer_is_stale(self):
        actor = self.actor(FakeClient(delay=.03), ttl=.01)
        self.assertTrue(actor.offer(state(), time.monotonic()))
        answer = actor.wait_result()
        self.assertTrue(answer['stale'])
        self.assertFalse(answer['actionable'])

    def test_region_rejection_is_terminal_and_has_safe_reason(self):
        class APIError(RuntimeError):
            status=451
            body={'title':'Typesafe is not available in your region.'}
        class Broken(FakeClient):
            def system_one(self,**kwargs):raise APIError()
        actor=self.actor(Broken())
        actor.offer(state(),time.monotonic())
        answer=actor.wait_result()
        self.assertEqual(answer['error_category'],'access_policy')
        self.assertIn('region',answer['error_message'])
        self.assertTrue(answer['terminal_error'])
        self.assertFalse(actor.offer(state(),time.monotonic()))

    def test_transient_failure_backoff_then_recovery(self):
        actor=self.actor(FakeClient(fail_once=True))
        actor.offer(state(),time.monotonic())
        answer=actor.wait_result()
        self.assertTrue(answer['retryable'])
        self.assertFalse(answer['terminal_error'])
        self.assertFalse(actor.offer(state(),time.monotonic()))
        time.sleep(.12)
        self.assertTrue(actor.offer(state(),time.monotonic()))
        self.assertEqual(actor.wait_result()['source'],'jev')

    def test_unknown_path_vetoed(self):
        actor = self.actor(FakeClient(maneuver='gap_left'))
        self.assertTrue(actor.offer(state(), time.monotonic()))
        answer = actor.wait_result()
        self.assertEqual(answer['maneuver'], 'gap_left')
        self.assertEqual(answer['effective_maneuver'], 'brake')
        self.assertFalse(answer['actionable'])

    def test_unchanged_cache_does_not_refresh_age(self):
        actor = self.actor(FakeClient())
        self.assertTrue(actor.offer(state(), time.monotonic()))
        first = actor.wait_result()['observation_age_s']
        self.assertFalse(actor.offer(state(), time.monotonic()))
        self.assertGreaterEqual(actor.read()['observation_age_s'], first)

    def test_http_failure_has_diagnostic_status_not_model_decision(self):
        class APIError(RuntimeError):status=503
        class Broken(FakeClient):
            def system_one(self,**kwargs):raise APIError('not logged')
        actor=self.actor(Broken())
        actor.offer(state(),time.monotonic())
        answer=actor.wait_result()
        self.assertEqual(answer['source'],'error')
        self.assertEqual(answer['error_http_status'],503)
        self.assertEqual(answer['error_category'],'server')
        self.assertFalse(answer['actionable'])

    def test_repeated_transient_errors_stop_at_limit(self):
        class APIError(RuntimeError):status=503
        class Broken(FakeClient):
            def system_one(self,**kwargs):raise APIError()
        actor=self.actor(Broken(),budget=5)
        for index in range(3):
            if index:time.sleep(.1*2**(index-1)+.03)
            self.assertTrue(actor.offer(state(),time.monotonic()))
            answer=actor.wait_result()
        self.assertTrue(answer['terminal_error'])
        self.assertFalse(actor.offer(state(),time.monotonic()))
        self.assertEqual(actor.stats()['attempts'],3)

    def test_error_message_redacts_known_credentials(self):
        class APIError(RuntimeError):
            status=451
            body={'title':'Denied secret-value https://example.com/secret Bearer abc'}
        class Broken(FakeClient):
            def system_one(self,**kwargs):raise APIError()
        actor=Tactician({'TYPESAFE_API_KEY':'secret-value'},client=Broken())
        self.addCleanup(actor.close)
        actor.offer(state(),time.monotonic())
        message=actor.wait_result()['error_message']
        self.assertNotIn('secret-value',message)
        self.assertNotIn('example.com',message)
        self.assertNotIn('Bearer abc',message)


if __name__ == '__main__':
    unittest.main()
