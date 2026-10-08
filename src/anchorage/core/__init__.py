"""Orchestration between the Docker layer and the UI: threads, stores, sessions.

Startup order: ``TaskRunner``, then ``EngineService``, then the stores
(``ContainerStore``, ``ImageStore``) wired to the engine, then ``engine.start()``.

Shutdown order:

1. ``dispose()`` every ``LogSession`` and ``StatsSession``.
2. ``ImageStore.shutdown()`` to stop live pull jobs.
3. ``EngineService.stop()``.
4. ``TaskRunner.close()``.
5. ``QThreadPool.globalInstance().waitForDone(2000)``.

Workers that miss the two-second deadline are handed to the application and deleted
when their thread returns, so destroying their former owner stays safe.

``LogSession``, ``StatsSession`` and ``PullJob`` are single-use: create a new object to
restart. ``stop()`` or ``cancel()`` before ``start()`` never emits ``ended``.
"""
