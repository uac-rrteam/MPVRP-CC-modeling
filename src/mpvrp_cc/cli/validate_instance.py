from __future__ import annotations

import argparse
import logging
from pathlib import Path
from mpvrp_cc.generation.instance_file_io import load_instance_file
from mpvrp_cc.generation.config import VerificationReport
from mpvrp_cc.generation.validation import validate_parsed_instance

LOGGER = logging.getLogger("mpvrp_cc.validate_instance")


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def log_report(report: VerificationReport, logger: logging.Logger = LOGGER) -> None:
    for message in report.infos:
        logger.info(message)
    for message in report.warnings:
        logger.warning(message)
    if report.errors:
        for message in report.errors:
            logger.error(message)
        logger.error("Status: INVALID (%d error(s), %d warning(s)).", len(report.errors), len(report.warnings))
    else:
        logger.info("Status: VALID (%d warning(s)).", len(report.warnings))


def verify_instance(filepath: str | Path, logger: logging.Logger = LOGGER) -> VerificationReport:
    path = Path(filepath)
    report = VerificationReport()
    logger.info("Verifying instance: %s", path)
    instance = load_instance_file(path, report)
    if instance is not None:
        parsed_report = validate_parsed_instance(instance)
        report.errors.extend(parsed_report.errors)
        report.warnings.extend(parsed_report.warnings)
        report.infos.extend(parsed_report.infos)
    return report


class InstanceValidator:
    def __init__(self, filepath: str | Path, logger: logging.Logger | None = None):
        self.filepath = Path(filepath)
        self.logger = logger or LOGGER
        self.report = VerificationReport()

    def verify(self) -> bool:
        self.report = verify_instance(self.filepath, self.logger)
        log_report(self.report, self.logger)
        return self.report.is_valid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an MPVRP-CC instance file for solver compatibility.")
    parser.add_argument("filepath", type=Path, help="Path to the .dat instance file.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(verbose=args.verbose, quiet=args.quiet)
    report = verify_instance(args.filepath)
    log_report(report)
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
