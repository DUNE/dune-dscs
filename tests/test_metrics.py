import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from asyncua import ua
from pysnmp.proto import errind

from dune_dscs.bridge_clients import PduClient
from dune_dscs.measure import request_timed_out
from dune_dscs.metrics import Distribution, PollStats, ProcessSampler, write_json


class MetricsTests(unittest.TestCase):
    def test_opcua_service_timeout_is_not_a_decode_error(self):
        self.assertTrue(request_timed_out(ua.UaStatusCodeError(ua.StatusCodes.BadTimeout)))
        self.assertFalse(request_timed_out(ua.UaStatusCodeError(ua.StatusCodes.BadNodeIdUnknown)))

    def test_bounded_percentiles_keep_lifetime_counts(self):
        stats = Distribution(3)
        self.assertIsNone(stats.snapshot()['p99'])
        for value in (100, 1, 2, 3):
            stats.add(value)
        result = stats.snapshot()
        self.assertEqual(result['count'], 4)
        self.assertEqual(result['window_count'], 3)
        self.assertEqual((result['mean'], result['max'], result['p50'], result['p99']), (26.5, 100, 2, 3))

    def test_timeouts_errors_and_overruns_are_separate(self):
        stats = PollStats()
        timings = {name: 1 for name in stats.timings}
        stats.record(timings, None, 1)
        stats.record({**timings, 'total_ms': 1500}, TimeoutError(), 1)
        stats.record(timings, ValueError(), 1)
        result = stats.snapshot()
        self.assertEqual((result['polls'], result['successes'], result['failures'], result['timeouts'],
                          result['overruns']), (3, 1, 2, 1, 1))

    @unittest.skipUnless(Path('/proc/self/stat').exists(), 'Linux process sampling')
    def test_live_process_and_exited_process(self):
        sampler = ProcessSampler(os.getpid())
        first, second = sampler.sample(), sampler.sample()
        self.assertEqual(first['status'], 'running')
        self.assertGreater(first['rss_mib'], 0)
        self.assertGreaterEqual(first['peak_rss_mib'], first['rss_mib'])
        self.assertIsNone(first['cpu_percent_one_core'])
        self.assertIsNotNone(second['cpu_percent_one_core'])
        process = subprocess.Popen([sys.executable, '-c', 'pass'])
        process.wait()
        self.assertEqual(ProcessSampler(process.pid).sample()['status'], 'unavailable')

    def test_atomic_report_refuses_overwrite_and_leaves_no_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.json'
            write_json(path, {'count': 1}, replace=False)
            with self.assertRaises(FileExistsError):
                write_json(path, {'count': 2}, replace=False)
            self.assertEqual(json.loads(path.read_text()), {'count': 1})
            write_json(path, {'count': 3})
            self.assertEqual(json.loads(path.read_text()), {'count': 3})
            self.assertEqual(list(Path(directory).iterdir()), [path])


class NativeTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_snmp_timeout_indication_becomes_timeout_error(self):
        reader = PduClient('127.0.0.1', 1161, 'private', None, 1)
        reader.target = object()
        reply = AsyncMock(return_value=(errind.requestTimedOut, 0, 0, []))
        with patch('dune_dscs.bridge_clients.get_cmd', reply), self.assertRaises(TimeoutError):
            await reader.read(['1.3.6.1.4.1.13742.6.3.2.2.1.4.1'])
