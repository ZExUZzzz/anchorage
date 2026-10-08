# Backend comparison

CPU: AMD Ryzen 9 7900X3D 12-Core Processor; kernel: 7.2.8-2-cachyos; Python: 3.12.14; PySide6: 6.11.2; docker-py: 7.2.0

## Method

- Run date (UTC): 2026-10-04 13:44
- Docker Engine 29.8.2, API 1.56; 4 containers and 13 images on the daemon
- Single run, backends measured sequentially (native first).
- Samples per row: 200/200/100/100 for the latency rows, 5 for the stats and import rows, 1 for the pause event and the live cancellation rows.
- The native client opens a UNIX connection per request while docker-py reuses pooled keep-alive connections, which explains most of the latency difference.

## Code and dependencies

| Backend | Lines (non-blank) | Dependencies, MiB | Import time, ms |
|---|---|---|---|
| native | 277 (transport.py) | 0 | 29 |
| docker-py | 261 (dockerpy.py) | 2.4 | 62 |
| shared | 876 (client.py, models.py, streams.py, errors.py, _time.py) | - | - |

Import time is the median of 5 runs of `-X importtime` (cumulative, last line). `client.py` holds the shared `Stream` and `EngineAPI` plus the native `DockerClient`, so it is counted in the shared row; dependency size is the sum of installed files of docker, requests, urllib3, charset_normalizer, idna, certifi.

## Call latency

| Operation | native median, ms | native p95, ms | docker-py median, ms | docker-py p95, ms |
|---|---|---|---|---|
| list_containers x200 | 5.92 | 7.33 | 6.03 | 7.51 |
| inspect_container x200 | 0.16 | 0.22 | 0.30 | 0.37 |
| list_images x100 | 25.94 | 27.44 | 26.00 | 27.40 |
| version x100 | 2.31 | 2.54 | 2.54 | 2.91 |

## Streaming

| Measurement | native | docker-py |
|---|---|---|
| first stats sample, warm collector, median of 5, ms | 1.2 | 1.7 |
| tail=1000 logs of the busiest running container, ms | 4.3 (1000 lines) | 4.5 (1000 lines) |
| first event after docker pause (includes CLI spawn), ms | 23.4 | 13.0 |

## Cancellation and daemon loss

| Measurement | native | docker-py |
|---|---|---|
| live: reader return after close() while blocked in a body read | 0 ms | 0 ms |
| fake daemon aborts the connection mid-stream: reader return | 6 ms (ProtocolError) | 6 ms (ended quietly) |

`FakeDaemon.stop()` does not drop open connections, so the daemon loss is simulated: the route aborts the socket once `stop()` has returned.

A read blocked before the response headers arrive (the `events()` request itself) cannot be interrupted by `close()`; a read blocked in the response body returns because the backend shuts the socket down before closing the response.

## Application footprint

| Backend | RSS after 20 s, MiB | CPU time, s |
|---|---|---|
| native | 89.8 | 0.16 |
| docker-py | 104.5 | 0.21 |

## Findings from implementation (static notes, not measured by this script)

- docker-py's default request timeout also applies to streamed reads unless disabled; the backend passes `timeout=None` for logs and stats.
- docker-py drops `force` in `APIClient.remove_volume`; the backend calls the private `_delete` instead.
- docker-py leaks a socket when a connect fails.
- docker-py's public `logs(stream=True)` loses the stdout/stderr frame type; the backend uses the private `_get` and demultiplexes itself.
- `events()` sends its request in the caller's thread, so it can block there.
- A read blocked before the response headers arrive (the `events()` request itself) cannot be interrupted; body reads return because the backend shuts the socket down before closing the response.
- `decode=True` streams (events, pull) end silently on a truncated chunked body; logs and stats, which read the raw response, raise `ProtocolError` (see the fake-daemon row above).
- The daemon answers the first stats sample in about 1 ms from a warm collector and in about 1 s from a cold one (manual probe, both backends alike); the table measures the warm case.

## Conclusions

- Both backends pass the same contract tests against the fake daemon and the same integration
  tests against a live daemon, so the application behaves the same on either one.
- Speed is a wash. Every latency row differs by less than a millisecond, which a GUI cannot
  show; docker-py's connection pooling buys nothing that matters here.
- docker-py costs more at runtime: about 15 MiB more RSS, twice the import time, 2.4 MiB of
  dependencies (docker, requests, urllib3 and their companions) and a `<8` pin.
- docker-py did not save code. `dockerpy.py` is as long as `transport.py`, because the
  application needs stream cancellation, stderr-aware log frames, a read timeout that does not
  apply to followed streams and precise error types, none of which the public docker-py API
  provides. The backend therefore touches four private members (`_get`, `_url`,
  `_raise_for_status`, `_delete`) and works around upstream defects (`remove_volume` drops
  `force`, a socket leaks on a failed connect, streamed reads inherit the request timeout).
- Robustness favours the native client: it raises `ProtocolError` on every truncated stream,
  while docker-py's decoded streams (events, pull) end silently; a docker-py request still
  waiting for response headers cannot be interrupted.

Decision: the native client is the default and the supported backend. The docker-py backend is
an experimental `--backend dockerpy` option so the comparison can be reproduced.
