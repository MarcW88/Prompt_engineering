import unittest

from collection_worker import CollectionWorker


class FakeDb:
    def __init__(self, jobs):
        self.jobs = jobs
        self.rpc_calls = []
        self.requests = []

    def rpc(self, function, body):
        self.rpc_calls.append((function, body))
        return self.jobs

    def request(self, method, table, query="", body=None, prefer="return=representation"):
        self.requests.append((method, table, query, body, prefer))
        return []


def worker(jobs):
    instance = CollectionWorker.__new__(CollectionWorker)
    instance.db = FakeDb(jobs)
    instance.config_path = "config/decathlon.yaml"
    instance.worker_id = "worker-test"
    instance.cloud_execution_id = "execution-test"
    return instance


class WorkerRuntimeTests(unittest.TestCase):
    def test_claims_explicit_job_atomically(self):
        instance = worker([])
        self.assertIsNone(instance.claim("job-1"))
        function, body = instance.db.rpc_calls[0]
        self.assertEqual(function, "claim_job")
        self.assertEqual(body["p_job_id"], "job-1")
        self.assertEqual(body["p_worker_id"], "worker-test")

    def test_returns_false_when_job_is_already_claimed(self):
        instance = worker([])
        self.assertFalse(instance.run_once("job-1"))
        self.assertEqual(instance.db.requests, [])

    def test_completes_claimed_job(self):
        job = {"id": "job-1", "kind": "collect_sources", "project_id": "project-1", "attempt_count": 1, "max_attempts": 3}
        instance = worker([job])
        instance._collect = lambda _: {"imported": 2}
        self.assertTrue(instance.run_once("job-1"))
        final = instance.db.requests[-1]
        self.assertEqual(final[0:2], ("PATCH", "jobs"))
        self.assertEqual(final[3]["status"], "completed")
        self.assertEqual(final[3]["output"], {"imported": 2})

    def test_requeues_recoverable_failure(self):
        job = {"id": "job-1", "kind": "collect_sources", "project_id": "project-1", "attempt_count": 1, "max_attempts": 3}
        instance = worker([job])
        instance._collect = lambda _: (_ for _ in ()).throw(RuntimeError("temporary"))
        with self.assertRaises(RuntimeError):
            instance.run_once("job-1")
        self.assertEqual(instance.db.requests[-1][3]["status"], "pending")

    def test_marks_last_failure_as_failed(self):
        job = {"id": "job-1", "kind": "collect_sources", "project_id": "project-1", "attempt_count": 3, "max_attempts": 3}
        instance = worker([job])
        instance._collect = lambda _: (_ for _ in ()).throw(RuntimeError("permanent"))
        with self.assertRaises(RuntimeError):
            instance.run_once("job-1")
        self.assertEqual(instance.db.requests[-1][3]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
