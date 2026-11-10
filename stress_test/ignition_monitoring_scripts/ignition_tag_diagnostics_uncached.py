def handleTimerEvent():
    """Collect uncached tag diagnostics and timer-section CPU timings."""
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

    try:
        if not os.path.exists(CONTROL_FILE):
            return

        with open(CONTROL_FILE, "r") as handle:
            control = json.load(handle)

        if not control.get("active", False):
            return

        device_count = int(control["N"])
        run_id = control["run_id"]

        if not 1 <= device_count <= 1000:
            raise ValueError("N must be between 1 and 1000")

        if not os.path.isdir(RESULTS_DIR):
            os.makedirs(RESULTS_DIR)

        started = System.nanoTime()

        # Measure elapsed and timer-thread CPU time separately.
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

        tick_utc = str(Instant.now())
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

        # Match the bridge's make_devices() ordering.
        hosts = [3, 6, 7, 2, 9, 10, 11, 12, 14]

        folders = []
        expected_paths = []

        for device_index in range(device_count):
            tpc = hosts[device_index % len(hosts)]
            device_number = device_index // len(hosts) + 1

            folder = "Weber%02d_Emulator%03d" % (tpc, device_number)
            tags = []

            for name, field, index in [
                ("Temperature", "Temp1", 0),
                ("Voltage1", "vol1", 0),
                ("Voltage2", "vol1", 1),
            ]:
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

                expected_paths.append(
                    TAG_ROOT + "/" + folder + "/" + name
                )

            folders.append({
                "name": folder,
                "tagType": "Folder",
                "tags": tags,
            })

        # Rebuild tag definitions and paths on every timer execution.
        mark("build_tag_lists")

        state = system.util.getGlobals()
        run_key = "BridgeStressMonitor.currentRun"
        reconfigured = state.get(run_key) != run_id

        if reconfigured:
            if system.tag.exists(TAG_ROOT):
                results = system.tag.deleteTags([TAG_ROOT])

                if any(not result.isGood() for result in results):
                    raise RuntimeError(
                        "Could not remove previous test tags"
                    )

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

            state[run_key] = run_id

        # Create the tags only when a new run starts.
        mark("configure_if_new_run")

        browsed = system.tag.browse(
            TAG_ROOT,
            {"recursive": True, "tagType": "AtomicTag"},
        ).getResults()

        existing = set(str(tag["fullPath"]) for tag in browsed)
        expected = set(expected_paths)

        present = [
            path for path in expected_paths if path in existing
        ]

        missing = len(expected - existing)
        extra = len(existing - expected)

        # Browse and check completeness on every timer execution.
        mark("browse_and_check_paths")

        values = (
            system.tag.readBlocking(present, 2000)
            if present else []
        )

        # Read the expected tags that are currently present.
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

        # Count quality and check the OPC UA connection.
        mark("quality_and_connection")

        # Avoid logging a sample from a run that ended or changed.
        with open(CONTROL_FILE, "r") as handle:
            latest = json.load(handle)

        if (
            not latest.get("active", False)
            or latest["run_id"] != run_id
        ):
            return

        # Recheck that this sample still belongs to the active run.
        mark("recheck_control")

        new_file = (
            not os.path.exists(DIAGNOSTICS_FILE)
            or os.path.getsize(DIAGNOSTICS_FILE) == 0
        )

        with open(DIAGNOSTICS_FILE, "ab") as handle:
            writer = csv.writer(handle)

            if new_file:
                writer.writerow([
                    "time_utc", "run_id", "N", "expected_tags",
                    "missing_tags", "extra_tags", "good_tags",
                    "uncertain_tags", "bad_tags", "connection_state",
                    "collector_ms",
                ])

            writer.writerow([
                str(Instant.now()), run_id, device_count, 3 * device_count,
                missing, extra, good, uncertain, bad, connection,
                round(collector_ms, 3),
            ])

        # Include diagnostic CSV writing in the section timings.
        mark("diagnostics_output")

        # Write the profiling rows after timing all diagnostic sections.
        new_profile = (
            not os.path.exists(PROFILE_FILE)
            or os.path.getsize(PROFILE_FILE) == 0
        )

        with open(PROFILE_FILE, "ab") as handle:
            writer = csv.writer(handle)

            if new_profile:
                writer.writerow([
                    "tick_utc", "run_id", "N", "reconfigured",
                    "section", "wall_ms", "timer_thread_cpu_ms",
                ])

            for section, wall_ms, cpu_ms in timings:
                writer.writerow([
                    tick_utc, run_id, device_count, int(reconfigured),
                    section, round(wall_ms, 3),
                    round(cpu_ms, 3) if cpu_ms != "" else "",
                ])

    except Exception as error:
        logger.error(str(error))
