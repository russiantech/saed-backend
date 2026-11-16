import json
from pathlib import Path

from django.core.management.base import BaseCommand

from saed.apidocs.builder import build_spec
from saed.apidocs.markdown import render_markdown


class Command(BaseCommand):
    help = "Write openapi.json and API.md (default: ../docs)."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="../docs", help="Output directory")

    def handle(self, *args, **opts):
        out = Path(opts["out"])
        out.mkdir(parents=True, exist_ok=True)
        spec = build_spec()
        (out / "openapi.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (out / "API.md").write_text(render_markdown(spec), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {out/'openapi.json'} and {out/'API.md'}"))
