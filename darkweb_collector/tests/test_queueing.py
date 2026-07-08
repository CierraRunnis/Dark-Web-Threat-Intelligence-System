from __future__ import annotations

import unittest

from darkweb_collector.queueing import build_worker_command


class QueueingTests(unittest.TestCase):
    def test_worker_command_sets_unique_hostname(self) -> None:
        command = build_worker_command("seed_http")

        self.assertIn("--hostname", command)
        hostname = command[command.index("--hostname") + 1]
        self.assertTrue(hostname.startswith("seed_http-"))
        self.assertNotIn("@celery", hostname)


if __name__ == "__main__":
    unittest.main()
