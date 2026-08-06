import sys
import os
import shutil
import subprocess
import math
import connect_python

# Stats parsing + Nominal streaming live in sibling modules; import softly so a
# missing module never aborts a run.
try:
    import gem5stats_core
    _stats_err = None
except Exception as e:  # pragma: no cover
    gem5stats_core, _stats_err = None, e
try:
    import gem5_nominal
    _nominal_err = None
except Exception as e:  # pragma: no cover
    gem5_nominal, _nominal_err = None, e

# Connect captures this logger into the LOGS panel (module function). Fall back to print.
try:
    _logger = connect_python.get_logger("autotest_connect")
    def log(msg):
        _logger.info(str(msg))
except Exception:
    def log(msg):
        print(msg)


def _resolve_docker(name):
    """Connect's process PATH usually lacks Docker Desktop's CLI; find it explicitly."""
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for cand in (shutil.which(name),
                 "/usr/local/bin/docker",
                 "/opt/homebrew/bin/docker",
                 "/Applications/Docker.app/Contents/Resources/bin/docker"):
        if cand and os.path.exists(cand):
            return cand
    return name  # not found -> will error with a clear message below


# ---- Docker setup (gem5 is the Linux build in a container) -- EDIT to match your run ----
DOCKER_BIN         = _resolve_docker("docker")
DOCKER_IMAGE       = "ghcr.io/gem5/ubuntu-24.04_all-dependencies:v24-0"
DOCKER_PLATFORM    = None                   # image is native arm64; no --platform needed
HOST_GEM5_DIR      = "/Users/ananda/archSim-nom/gem5"   # host path to gem5 source (where build/ + configs/ live)
CONTAINER_GEM5_DIR = "/gem5"                # mount point + working dir in the container

DEFAULT_TOPOLOGY = "Mesh_XY"
MEM_SIZE = "2048MB"
SIM_CYCLES = 10000000


def orionPower(power_model, *args):
    return {"total_avg_power_mw": 100.0, "total_energy_pj": 500.0,
            "peak_ctrl_id": "ctrl0", "peak_ctrl_power_mw": 20.0}


def _docker_env():
    # Connect's process PATH is stripped; Docker's credential helper
    # (docker-credential-desktop) lives in these dirs, so add them.
    env = dict(os.environ)
    extra = "/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin"
    env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    return env


def docker_wrap(gem5_cmd):
    cmd = [DOCKER_BIN, "run", "--rm"]
    if DOCKER_PLATFORM:
        cmd += ["--platform", DOCKER_PLATFORM]
    cmd += ["-v", f"{HOST_GEM5_DIR}:{CONTAINER_GEM5_DIR}", "-w", CONTAINER_GEM5_DIR, DOCKER_IMAGE]
    return cmd + gem5_cmd


def _host_stats_dir(output_dir, subdir=""):
    """Map the container --outdir (relative to /gem5) to the host path so we can
    read stats.txt that the container wrote through the volume mount."""
    od = output_dir
    if od.startswith("./"):
        od = od[2:]
    od = od.lstrip("/")                      # treat as relative to the gem5 root
    return os.path.join(HOST_GEM5_DIR, od, subdir) if subdir else os.path.join(HOST_GEM5_DIR, od)


def runtest(gem5_bin, config_script, output_dir, num_cpus, num_dirs, injection_rate,
            topology=DEFAULT_TOPOLOGY, program="", program_options="", enable_power=False,
            run_subdir=None):
    """Run one gem5 invocation. Returns (ok: bool, host_stats_dir: str).

    Each run writes to its own subdir so a sweep's stats.txt files don't overwrite
    each other and can be parsed individually.
    """
    container_outdir = f"{output_dir}/{run_subdir}" if run_subdir else output_dir
    host_stats_dir = _host_stats_dir(output_dir, run_subdir or "")

    gem5_cmd = [
        gem5_bin,
        f"--outdir={container_outdir}",
        config_script,
        f"--num-cpus={num_cpus}",
        f"--num-dirs={num_dirs}",
        f"--mem-size={MEM_SIZE}",
        "--network=garnet",
        f"--topology={topology}",      # gem5 loads configs/topologies/<topology>.py
        f"--sim-cycles={SIM_CYCLES}",
        "--synthetic=uniform_random",
        f"--injectionrate={injection_rate}",
    ]
    if topology in ("FractalMesh", "Mesh_XY", "Torus"):
        rows = max(r for r in range(1, math.isqrt(num_cpus) + 1) if num_cpus % r == 0)
        gem5_cmd.append(f"--mesh-rows={rows}")
    # only for an actual SE workload -- NOT a topology file. Leave Program Path blank for synthetic NoC.
    if program:
        log(f"program set ({program!r}); appending -c/-o -- this should be an SE workload, not a topology file")
        gem5_cmd += ["-c", program]
        if program_options:
            gem5_cmd += ["-o", program_options]

    cmd = docker_wrap(gem5_cmd)
    log(f"COMMAND = {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=_docker_env())
    except FileNotFoundError as e:
        log(f"CANNOT START: {e}")
        log(f"-> '{DOCKER_BIN}' not found. Set DOCKER_BIN to the full docker path "
            f"(find it with `which docker` in a terminal).")
        sys.exit(1)   # docker missing is unrecoverable; stop the whole sweep

    if result.stdout:
        log("[gem5 stdout]\n" + result.stdout[-4000:])
    if result.stderr:
        log("[gem5 stderr]\n" + result.stderr[-4000:])

    if result.returncode != 0:
        log(f"gem5 FAILED (rc={result.returncode}) for {topology} at injection_rate={injection_rate}")
        return False, host_stats_dir   # let the sweep continue past a single failed point

    log(f"SUCCESS: {topology} at injection_rate={injection_rate}")
    if enable_power:
        log(f"power: {orionPower('orion', output_dir, topology, num_cpus, injection_rate)}")
    return True, host_stats_dir


@connect_python.main
def main(nominal_client: connect_python.Client):
    log("main() started -- reading widget values")

    gem5_bin        = nominal_client.get_value("gem5_binary")
    config_script   = nominal_client.get_value("config_script")
    program         = nominal_client.get_value("program") or ""
    program_options = nominal_client.get_value("program_options") or ""
    output_dir      = nominal_client.get_value("output_dir")
    num_cpus        = int(float(nominal_client.get_value("num_nodes")))   # widget id is num_nodes
    num_dirs        = num_cpus
    start           = float(nominal_client.get_value("injection_start"))
    stop            = float(nominal_client.get_value("injection_stop"))
    step            = float(nominal_client.get_value("injection_step"))
    enable_power    = str(nominal_client.get_value("enable_power_models")).lower() in ("true", "1", "yes")
    topology        = nominal_client.get_value("topology") or DEFAULT_TOPOLOGY

    log(f"DOCKER_BIN={DOCKER_BIN!r}")
    log(f"gem5_binary={gem5_bin!r} config_script={config_script!r} output_dir={output_dir!r}")
    log(f"program={program!r} program_options={program_options!r}")
    log(f"num_cpus={num_cpus} topology={topology!r} power={enable_power}")
    log(f"injection start/stop/step = {start} / {stop} / {step}")

    if step <= 0:
        rates = [start]
    else:
        rates, r = [], start
        while r <= stop + 1e-9:
            rates.append(round(r, 6))
            r += step
    log(f"sweep rates ({len(rates)}): {rates}")

    # open a live Nominal stream up front so points appear as each run finishes
    streamer = None

    results_json = os.path.join(os.getcwd(), "results.json")
    parsed = 0
    failures = 0

    try:
        for i, injection_rate in enumerate(rates, 1):
            subdir = f"{topology}_inj{injection_rate}"
            log(f"=== run {i}/{len(rates)} : {topology} @ {injection_rate}  (outdir {output_dir}/{subdir}) ===")
            ok, host_dir = runtest(gem5_bin, config_script, output_dir, num_cpus, num_dirs, injection_rate,
                                   topology=topology, program=program,
                                   program_options=program_options, enable_power=enable_power,
                                   run_subdir=subdir)
            if not ok:
                failures += 1
                log(f"skipping stats parse for failed run @ {injection_rate}")
                continue

            if gem5stats_core is None:
                log(f"gem5stats_core not importable ({_stats_err}); cannot parse stats")
                continue

            stats_path = os.path.join(host_dir, "stats.txt")
            if not os.path.exists(stats_path):
                log(f"WARN: no stats.txt at {stats_path}; skipping parse")
                continue
            try:
                flat = gem5stats_core.parse_stats(stats_path)
                record = gem5stats_core.to_record(flat, topology, injection_rate, SIM_CYCLES)
                gem5stats_core.cache_record(record, json_path=results_json)
                parsed += 1
                log(f"parsed @ {injection_rate}: pkt_lat={flat['average_packet_latency']} "
                    f"flit_lat={flat['average_flit_latency']} recv={flat['packets_received']} "
                    f"-> cached to {results_json}")
            except Exception as e:
                log(f"parse error for {stats_path}: {e}")
                continue

            # push this point to Nominal in real time
            if streamer is not None:
                try:
                    streamer.send(flat, injection_rate)
                except Exception as e:
                    log(f"nominal stream send failed @ {injection_rate}: {e}")
    finally:
        if streamer is not None:
            try:
                streamer.close()
            except Exception as e:
                log(f"nominal stream close: {e}")

    log(f"all runs complete ({len(rates) - failures} ok, {failures} failed; {parsed} parsed into results.json)")
    if streamer is not None:
        log("live run created in Nominal -- open it and click Go Live to watch the sweep")
    elif parsed:
        log("results cached -- click 'Send to core' to push this topology to Nominal")


if __name__ == "__main__":
    main()