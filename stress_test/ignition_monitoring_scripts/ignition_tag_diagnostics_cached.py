def handleTimerEvent():
    """Collect cached tag diagnostics and timer-section CPU timings."""
    import csv
    import json
    import os

    from java.lang import System
    from java.lang.management import ManagementFactory
    from java.time import Instant

    BASE_DIR = "/uni-mainz.de/homes/lgoncalve/dune-dscs/stress_test"
    RESULTS_DIR = os.path.join(BASE_DIR, "results")
    CONTROL_FILE = os.path.join(BASE_DIR, "ignition_test_control.json")
    DIAGNOSTICS_FILE = os.path.join(
        RESULTS_DIR, "ignition_tag_diagnostics.csv"
    )
    PROFILE_FILE = os.path.join(RESULTS_DIR, "ignition_timer_profile.csv")

    TAG_ROOT = "[default]BridgeStressTest"
    OPC_SERVER = "bridge leonor 09"

    logger = system.util.getLogger("BridgeStressMonitor")
    state = system.util.getGlobals()
    cache_key = "BridgeStressMonitor.cachedPaths"

    def check_paths(paths):
        """Count missing and extra atomic tag paths."""
        expected = set(paths)
        existing = set()

        if system.tag.exists(TAG_ROOT):
            browsed = system.tag.browse(
                TAG_ROOT, {"recursive": True, "tagType": "AtomicTag"}
            ).getResults()
            existing = set(str(tag["fullPath"]) for tag in browsed)

        return len(expected - existing), len(existing - expected)

    def audit_end(cached):
        """Report tag completeness when a cached run ends."""
        missing, extra = check_paths(cached["paths"])
        logger.info(
            "End of run %s: N=%d, missing=%d, extra=%d"
            % (cached["run_id"], cached["N"], missing, extra)
        )

    def append_rows(path, header, rows):
        """Append CSV rows, creating the header for a new file."""
        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "ab") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(header)
            writer.writerows(rows)

    try:
        if not os.path.exists(CONTROL_FILE):
            return

        with open(CONTROL_FILE, "r") as handle:
            control = json.load(handle)

        cached = state.get(cache_key)

        if not control.get("active", False):
            if cached is not None:
                audit_end(cached)
                del state[cache_key]
            return

        device_count = int(control["N"])
        run_id = control["run_id"]

        if not 1 <= device_count <= 1000:
            raise ValueError("N must be between 1 and 1000")

        if not os.path.isdir(RESULTS_DIR):
            os.makedirs(RESULTS_DIR)

        started = System.nanoTime()
        tick_utc = str(Instant.now())
        thread_bean = ManagementFactory.getThreadMXBean()
        cpu_available = (
            thread_bean.isCurrentThreadCpuTimeSupported()
            and thread_bean.isThreadCpuTimeEnabled()
        )

        def snapshot():
            cpu_ns = (
                thread_bean.getCurrentThreadCpuTime()
                if cpu_available else -1
            )
            return System.nanoTime(), cpu_ns

        previous = [snapshot()]
        timings = []

        def mark(section):
            wall_ns, cpu_ns = snapshot()
            old_wall_ns, old_cpu_ns = previous[0]

            cpu_ms = (
                (cpu_ns - old_cpu_ns) / 1000000.0
                if cpu_ns >= 0 and old_cpu_ns >= 0 else ""
            )
            timings.append((
                section,
                (wall_ns - old_wall_ns) / 1000000.0,
                cpu_ms,
            ))
            previous[0] = (wall_ns, cpu_ns)

        reconfigured = cached is None or cached["run_id"] != run_id

        if reconfigured:
            # Handle a new run arriving between two timer ticks.
            if cached is not None:
                audit_end(cached)
                del state[cache_key]
                mark("audit_previous_run")

            # Match the bridge's make_devices() order.
            hosts = [3, 6, 7, 2, 9, 10, 11, 12, 14]
            fields = [
                ("Temperature", "Temp1", 0),
                ("Voltage1", "vol1", 0),
                ("Voltage2", "vol1", 1),
            ]
            folders = []
            expected_paths = []

            for device_index in range(device_count):
                tpc = hosts[device_index % len(hosts)]
                device_number = device_index // len(hosts) + 1
                folder = "Weber%02d_Emulator%03d" % (tpc, device_number)
                tags = []

                for name, field, index in fields:
                    tags.append({
                        "name": name,
                        "tagType": "AtomicTag",
                        "valueSource": "opc",
                        "dataType": "Double",
                        "enabled": True,
                        "tagGroup": "Default",
                        "opcServer": OPC_SERVER,
                        "opcItemPath": (
                            "nsu=;s=TPC%d/WIB%d/%s/%d"
                            % (tpc, device_number, field, index)
                        ),
                    })
                    expected_paths.append(TAG_ROOT + "/" + folder + "/" + name)

                folders.append({
                    "name": folder,
                    "tagType": "Folder",
                    "tags": tags,
                })

            mark("build_tag_lists")

            if system.tag.exists(TAG_ROOT):
                results = system.tag.deleteTags([TAG_ROOT])
                if any(not result.isGood() for result in results):
                    raise RuntimeError("Could not remove previous test tags")

            results = system.tag.configure(
                "[default]",
                [{
                    "name": "BridgeStressTest",
                    "tagType": "Folder",
                    "tags": folders,
                }],
                "a",
            )
            if any(not result.isGood() for result in results):
                raise RuntimeError("Could not create test tags")

            mark("configure_if_new_run")

            missing, extra = check_paths(expected_paths)
            mark("browse_and_check_paths")

            cached = {
                "run_id": run_id,
                "N": device_count,
                "paths": expected_paths,
                "missing": missing,
                "extra": extra,
            }
            state[cache_key] = cached

            message = (
                "Start of run %s: N=%d, expected=%d, missing=%d, extra=%d"
                % (run_id, device_count, len(expected_paths), missing, extra)
            )
            if missing or extra:
                logger.error(message)
            else:
                logger.info(message)
            mark("log_setup_result")

        else:
            if cached["N"] != device_count:
                raise RuntimeError("N changed without a new run_id")
            mark("reuse_cached_paths")

        # Completeness counts come from the initial browse, not each tick.
        # A setup mismatch is reported in the Gateway log.
        if cached["missing"] or cached["extra"]:
            return

        values = system.tag.readBlocking(cached["paths"], 2000)
        mark("bulk_read")

        good = uncertain = bad = 0
        for value in values:
            if value.quality.isGood():
                good += 1
            elif value.quality.isUncertain():
                uncertain += 1
            else:
                bad += 1

        connection = system.opc.getServerState(OPC_SERVER)
        collector_ms = (System.nanoTime() - started) / 1000000.0
        mark("quality_and_connection")

        with open(CONTROL_FILE, "r") as handle:
            latest = json.load(handle)

        if (
            not latest.get("active", False)
            or latest["run_id"] != run_id
        ):
            return

        mark("recheck_control")

        append_rows(DIAGNOSTICS_FILE, [
            "time_utc", "run_id", "N", "expected_tags",
            "missing_tags", "extra_tags", "good_tags",
            "uncertain_tags", "bad_tags", "connection_state",
            "collector_ms",
        ], [[
            str(Instant.now()), run_id, device_count, len(cached["paths"]),
            cached["missing"], cached["extra"], good,
            uncertain, bad, connection, round(collector_ms, 3),
        ]])

        mark("diagnostics_output")

        append_rows(PROFILE_FILE, [
            "tick_utc", "run_id", "N", "reconfigured",
            "section", "wall_ms", "timer_thread_cpu_ms",
        ], [
            [
                tick_utc, run_id, device_count, int(reconfigured), section,
                round(wall_ms, 3),
                round(cpu_ms, 3) if cpu_ms != "" else "",
            ]
            for section, wall_ms, cpu_ms in timings
        ])

    except Exception as error:
        logger.error(str(error))
