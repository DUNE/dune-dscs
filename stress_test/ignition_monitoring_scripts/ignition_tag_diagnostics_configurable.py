def handleTimerEvent():
    """Configure test tags and collect diagnostics using the run settings."""
    import csv
    import json
    import os

    from java.lang import System
    from java.lang.management import ManagementFactory
    from java.time import Instant

    BASE_DIR = "/uni-mainz.de/homes/lgoncalve/dune-dscs/stress_test"
    CONTROL_FILE = os.path.join(BASE_DIR, "ignition_test_control.json")
    STATUS_FILE = os.path.join(BASE_DIR, ".runtime", "ignition_status.json")
    TAG_ROOT = "[default]BridgeStressTest"
    OPC_SERVER = "bridge leonor 09"

    logger = system.util.getLogger("BridgeStressMonitor")
    state = system.util.getGlobals()
    state_key = "BridgeStressMonitor.configurableRun"
    run_id = None

    def check_paths(paths):
        expected = set(paths)
        existing = set()
        if system.tag.exists(TAG_ROOT):
            tags = system.tag.browse(
                TAG_ROOT, {"recursive": True, "tagType": "AtomicTag"}
            ).getResults()
            existing = set(str(tag["fullPath"]) for tag in tags)
        present = [path for path in paths if path in existing]
        return len(expected - existing), len(existing - expected), present

    def audit_end(cached):
        missing, extra, _ = check_paths(cached["paths"])
        logger.info(
            "End of run %s: N=%d, missing=%d, extra=%d"
            % (cached["run_id"], cached["N"], missing, extra)
        )

    def write_status(ready, error=""):
        directory = os.path.dirname(STATUS_FILE)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        temporary = STATUS_FILE + ".tmp"
        with open(temporary, "w") as handle:
            json.dump({
                "run_id": run_id,
                "ready": ready,
                "error": error,
            }, handle)
        os.rename(temporary, STATUS_FILE)

    def append_rows(path, header, rows):
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

        cached = state.get(state_key)
        if not control.get("active", False):
            if cached is not None:
                audit_end(cached)
                del state[state_key]
            return

        run_id = control["run_id"]
        device_count = int(control["N"])
        timer_enabled = control.get("timer_enabled", True)
        cache_enabled = control.get("cache_enabled", True)
        results_dir = control.get(
            "output_dir", os.path.join(BASE_DIR, "results")
        )

        if not 1 <= device_count <= 1000:
            raise ValueError("N must be between 1 and 1000")
        if not isinstance(timer_enabled, bool):
            raise ValueError("timer_enabled must be a JSON boolean")
        if not isinstance(cache_enabled, bool):
            raise ValueError("cache_enabled must be a JSON boolean")
        if not os.path.isabs(results_dir):
            raise ValueError("output_dir must be an absolute path")

        settings = (device_count, timer_enabled, cache_enabled, results_dir)
        new_run = cached is None or cached["run_id"] != run_id
        if not new_run and cached["settings"] != settings:
            raise RuntimeError("Settings changed without a new run_id")

        # Disabled collection still uses a small control-file check.
        if not new_run and cached["ready"] and not timer_enabled:
            return

        if not os.path.isdir(results_dir):
            os.makedirs(results_dir)

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

        if new_run and cached is not None:
            audit_end(cached)
            del state[state_key]
            mark("audit_previous_run")

        # Match the device ordering in the bridge.
        if new_run or not cache_enabled:
            hosts = [3, 6, 7, 2, 9, 10, 11, 12, 14]
            fields = [
                ("Temperature", "Temp1", 0),
                ("Voltage1", "vol1", 0),
                ("Voltage2", "vol1", 1),
            ]
            folders = []
            paths = []

            for device_index in range(device_count):
                tpc = hosts[device_index % len(hosts)]
                number = device_index // len(hosts) + 1
                folder = "Weber%02d_Emulator%03d" % (tpc, number)
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
                            % (tpc, number, field, index)
                        ),
                    })
                    paths.append(TAG_ROOT + "/" + folder + "/" + name)
                folders.append({
                    "name": folder,
                    "tagType": "Folder",
                    "tags": tags,
                })
            mark("build_tag_lists")
        else:
            paths = cached["paths"]
            mark("reuse_cached_paths")

        if new_run:
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
            cached = {
                "run_id": run_id,
                "N": device_count,
                "settings": settings,
                "paths": paths,
                "ready": False,
            }
            state[state_key] = cached
        mark("configure_if_new_run")

        if new_run or not cache_enabled:
            missing, extra, present = check_paths(paths)
            cached.update(missing=missing, extra=extra, present=present)
            mark("browse_and_check_paths")
        else:
            missing = cached["missing"]
            extra = cached["extra"]
            present = cached["present"]

        if new_run and (missing or extra):
            raise RuntimeError(
                "Tag setup mismatch: missing=%d, extra=%d" % (missing, extra)
            )

        values = system.tag.readBlocking(present, 2000) if present else []
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
        if not latest.get("active", False) or latest["run_id"] != run_id:
            return
        mark("recheck_control")

        ready = (
            not missing and not extra and good == len(paths)
            and str(connection).upper() == "CONNECTED"
        )
        if new_run or ready != cached["ready"]:
            write_status(ready)
            mark("publish_status")
        cached["ready"] = ready

        if not timer_enabled:
            return

        diagnostics_file = os.path.join(
            results_dir, "ignition_tag_diagnostics.csv"
        )
        append_rows(diagnostics_file, [
            "time_utc", "run_id", "N", "expected_tags", "missing_tags",
            "extra_tags", "good_tags", "uncertain_tags", "bad_tags",
            "connection_state", "collector_ms",
        ], [[
            str(Instant.now()), run_id, device_count, len(paths), missing,
            extra, good, uncertain, bad, connection, round(collector_ms, 3),
        ]])
        mark("diagnostics_output")

        append_rows(os.path.join(results_dir, "ignition_timer_profile.csv"), [
            "tick_utc", "run_id", "N", "reconfigured", "section",
            "wall_ms", "timer_thread_cpu_ms",
        ], [
            [
                tick_utc, run_id, device_count, int(new_run), section,
                round(wall_ms, 3),
                round(cpu_ms, 3) if cpu_ms != "" else "",
            ]
            for section, wall_ms, cpu_ms in timings
        ])

    except Exception as error:
        logger.error(str(error))
        if run_id is not None:
            try:
                write_status(False, str(error))
            except Exception as status_error:
                logger.error(str(status_error))
