"""Deterministic Markdown digest rendering."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from radar.digest.models import Digest


def render_markdown(digest: Digest) -> str:
    """Render a digest using the reviewed package template."""
    template_directory = Path(__file__).parent / "templates"
    environment = Environment(
        loader=FileSystemLoader(template_directory),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("digest.md.j2").render(digest=digest)
