# Measure bridge behavior

## Live native polling metrics

```bash
uv run python -m dune_dscs.bridge examples/bridge.yaml --metrics runs/bridge.json
```

The optional JSON snapshot updates every five seconds and once on shutdown.
Use `--metrics-interval 1` for one-second snapshots. A write error is logged;
device polling continues. Give each bridge instance its own file.

The report contains totals, per-technology and per-device measurements:

| Measurement | Meaning |
|---|---|
| queue_ms | Waiting for a free polling slot |
| query_ms | The complete native device read, including all requested message groups |
| publish_ms | Updating that device's OPC UA nodes |
| total_ms | Complete poll, including queueing, conversion and publication |
| start_lateness_ms | Delay beyond the device's configured poll period |
| successes, failures, timeouts | Completed polls; timeouts are a subset of failures |
| overruns | Polls whose total time exceeds the configured period |
| event_loop_lag_ms | Delay in a task scheduled every 100 ms |

Native query timing includes failed attempts. A poll is one device acquisition,
not one UDP packet or protobuf message. Cancelled, incomplete polls at shutdown
are excluded. Error counts use exception names. Counters reset when the bridge
process restarts; the PID in the report identifies the process.

The process sample includes PID, CPU seconds, CPU percentage, resident memory
(RSS), peak RSS, thread count and open file descriptors. CPU 100% means one
logical CPU. Linux `/proc` supplies these values; children are excluded.
Peak RSS is the process lifetime peak, not a peak limited to the measurement.
The first CPU percentage is unknown until a second sample is available.
Unavailable processes and reused PIDs are reported explicitly.

## OPC UA query and resource probe

Run the bridge first, then:

```bash
uv run python -m dune_dscs.measure examples/bridge.yaml \
  --duration 30 --workers 4 --chunk-size 100 --output runs/read-001.json
```

The probe repeatedly reads the configured measurement nodes. Each worker keeps
one request in flight, using one shared OPC UA session. `--timeout` sets the
request timeout in seconds. `--kind` and `--endpoint` work as on the bridge CLI.
Add `--pid 12345` using the bridge PID from its metrics file. Repeat `--pid`
for several local processes. Without PIDs, resource sampling is omitted.

The report separates successful/failed request latency, request timeouts, good
and bad values, status codes and source-value age. Connection setup has its own
timing and timeout count. A successful OPC UA request may return bad-quality
measurements while a native device is unavailable; that is not a request timeout.
Throughput uses actual elapsed query time, including the last in-flight request.
Request latency includes transport and client decoding, and excludes the probe's
subsequent value-age accounting. It is not full-fleet snapshot latency.

Reports include source revision/dirty state, configuration SHA-256, settings,
host and dependency versions. Choose a new output filename for each run;
completed reports are never overwritten. `status: completed` means collection
finished, not that the error counts satisfy an acceptance requirement.

## Reading the statistics

Counts, means, minima and maxima cover the observed run. Percentiles use the
nearest-rank method on a bounded recent window: 256 samples for native timings
and resources, 4,096 for OPC UA query times and value ages. Every distribution
reports both lifetime count and window size. Resource histories retain the last
256 samples, with a separate total sample count. These are sample percentiles,
not confidence bounds. Negative value ages can indicate clock disagreement.

Metrics and the read probe add load. Compare runs with the same instrumentation,
device allocation, periods and concurrency. RSS includes shared pages, so adding
process RSS does not give unique host memory use. Running the probe on the bridge
host shares CPU and loopback networking. These tools measure the bridge and
OPC UA reads; they do not measure Ignition rendering or historian latency.
