"""Command-line entry point for deterministic experiment diagnosis."""

import argparse

from .experiment_analytics import (
    analyze_experiment,
    ExperimentDataError,
    write_analysis_artifacts,
)


def main(argv=None):
    """Analyze one verified experiment and write reproducible artifacts."""
    parser = argparse.ArgumentParser(
        description='Analyze a robot experiment without invoking an LLM.'
    )
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    try:
        analysis = analyze_experiment(args.manifest)
        artifacts = write_analysis_artifacts(analysis, args.output_dir)
    except ExperimentDataError as error:
        parser.exit(3, f'INVALID EXPERIMENT: {error}\n')
    print(
        f'ANALYZED: {analysis["run_id"]} '
        f'windows={len(analysis["anomaly_windows"])}'
    )
    for label, path in artifacts.items():
        print(f'{label}: {path}')


if __name__ == '__main__':
    main()
