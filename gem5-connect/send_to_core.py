"""Connect "Send to core" button: batch-push the cached gem5 results to Nominal.

Reads results.json (cached by Run gem5) and pushes the ENTIRE file -- one run per
topology -- to Nominal Core in one shot. Not live: run your sweeps first, then click this.
"""
import os
import connect_python
import gem5_nominal

try:
    _logger = connect_python.get_logger("send_to_core")
    def log(msg):
        _logger.info(str(msg))
except Exception:
    def log(msg):
        print(msg)

RESULTS_JSON = "results.json"


@connect_python.main
def main(client: connect_python.Client):
    log("send_to_core: batch-pushing cached gem5 results to Nominal Core")
    path = os.path.join(os.getcwd(), RESULTS_JSON)
    if not os.path.exists(path):
        log(f"no {RESULTS_JSON} at {path} -- run a sweep first (Run gem5 caches results there)")
        return
    try:
        runs = gem5_nominal.push_results_json(path, topology=None, log=log)  # whole file, every topology
        pushed = [r for r in runs if r is not None]
        log(f"done: pushed {len(pushed)} run(s) to Nominal (one per topology)")
        for r in pushed:
            log(f"  run {getattr(r, 'rid', '?')}")
    except Exception as e:
        log(f"nominal push FAILED: {e}")
        log("  -> ensure 'nominal' is in app.connect python.packages and your profile/workspace RID are valid.")


if __name__ == "__main__":
    main()