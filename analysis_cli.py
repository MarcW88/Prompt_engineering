#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from analysis.models import AnalysisRequest
from analysis.providers import BrightDataProvider, OxylabsProvider
from analysis.reconstruction import PromptReconstructor, ReconstructionExample
from storage import AnalysisStorage


def parse_args():
    parser = argparse.ArgumentParser(description="Prompt Finder reverse-engineering workflow")
    parser.add_argument("--db", default="./output/analysis/observations.db")
    commands = parser.add_subparsers(dest="command", required=True)

    observe = commands.add_parser("observe")
    observe.add_argument("prompt")
    observe.add_argument("--provider", choices=["brightdata", "oxylabs"], default="brightdata")
    observe.add_argument("--engine", default="chatgpt")
    observe.add_argument("--country", default="FR")
    observe.add_argument("--language", default="fr")

    reconstruct = commands.add_parser("reconstruct")
    reconstruct.add_argument("fan_outs", nargs="+")
    reconstruct.add_argument("--examples", type=Path)
    reconstruct.add_argument("--language", default="fr")
    reconstruct.add_argument("--limit", type=int, default=3)

    commands.add_parser("init-db")
    return parser.parse_args()


def load_examples(path: Path):
    records = json.loads(path.read_text(encoding="utf-8"))
    return [ReconstructionExample(
        prompt=record["prompt"],
        fan_outs=record["fan_outs"],
        source_reference=record.get("source_reference", ""),
    ) for record in records]


def main():
    args = parse_args()
    storage = AnalysisStorage(args.db)
    if args.command == "init-db":
        print(storage.db_path)
        return
    if args.command == "observe":
        providers = {"brightdata": BrightDataProvider(), "oxylabs": OxylabsProvider()}
        observation = providers[args.provider].execute(AnalysisRequest(
            prompt=args.prompt,
            engine=args.engine,
            country=args.country,
            language=args.language,
        ))
        storage.save_observation(observation)
        print(json.dumps({
            "id": observation.id,
            "provider": observation.provider,
            "engine": observation.engine,
            "fan_outs": observation.fan_outs,
            "citations": [citation.url for citation in observation.citations],
        }, ensure_ascii=False, indent=2))
        return
    examples = load_examples(args.examples) if args.examples else []
    candidates = PromptReconstructor(examples).reconstruct(args.fan_outs, args.language, args.limit)
    for candidate in candidates:
        storage.save_candidate(candidate)
    print(json.dumps([{
        "id": candidate.id,
        "prompt": candidate.text,
        "confidence": candidate.confidence,
        "method": candidate.metadata["method"],
    } for candidate in candidates], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
