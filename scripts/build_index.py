"""Build (or rebuild) the ICD-10 and CPT hybrid indexes on disk.

Usage:
    python -m scripts.build_index            # build whatever is missing
    python -m scripts.build_index --force    # rebuild even if cached
"""

from __future__ import annotations

import argparse
import shutil
import time

from medcoder.config import get_settings
from medcoder.logging_setup import configure_logging, get_logger, trace_context
from medcoder.retrieval.hybrid import get_retriever, reset_cache
from medcoder.schemas import CodeSystem


def main() -> None:
    parser = argparse.ArgumentParser(description="Build hybrid retrieval indexes.")
    parser.add_argument("--force", action="store_true", help="Wipe and rebuild from scratch.")
    parser.add_argument(
        "--system",
        choices=["icd10", "cpt", "both"],
        default="both",
        help="Which catalog to build.",
    )
    args = parser.parse_args()

    configure_logging()
    log = get_logger("build_index")
    s = get_settings()

    if args.force and s.index_dir.exists():
        log.info("wiping_index_dir", extra={"path": str(s.index_dir)})
        shutil.rmtree(s.index_dir)
        reset_cache()
    s.index_dir.mkdir(parents=True, exist_ok=True)

    systems: list[CodeSystem] = []
    if args.system in ("icd10", "both"):
        systems.append(CodeSystem.ICD10)
    if args.system in ("cpt", "both"):
        systems.append(CodeSystem.CPT)

    with trace_context() as tid:
        log.info("build_index_start", extra={"systems": [sys.value for sys in systems]})
        for system in systems:
            t0 = time.perf_counter()
            r = get_retriever(system)
            log.info(
                "system_ready",
                extra={
                    "system": system.value,
                    "n_entries": len(r.entries),
                    "elapsed_s": round(time.perf_counter() - t0, 2),
                },
            )
        log.info("build_index_done", extra={"trace_id": tid})


if __name__ == "__main__":
    main()
