"""Repository document discovery and safe decoding."""

import base64
import binascii
from dataclasses import dataclass

from radar.domain.errors import EntityParseError
from radar.domain.schemas import ContentDTO


@dataclass(frozen=True)
class DocumentSpec:
    document_type: str
    path: str


DOCUMENT_SPECS = (
    DocumentSpec("readme", "README"),
    DocumentSpec("contributing", "CONTRIBUTING.md"),
    DocumentSpec("contributing", ".github/CONTRIBUTING.md"),
    DocumentSpec("contributing", "docs/CONTRIBUTING.md"),
    DocumentSpec("code_of_conduct", "CODE_OF_CONDUCT.md"),
    DocumentSpec("code_of_conduct", ".github/CODE_OF_CONDUCT.md"),
    DocumentSpec("security", "SECURITY.md"),
    DocumentSpec("security", ".github/SECURITY.md"),
    DocumentSpec("issue_template", ".github/ISSUE_TEMPLATE/bug_report.md"),
    DocumentSpec("issue_template", ".github/ISSUE_TEMPLATE/feature_request.md"),
    DocumentSpec("issue_template_config", ".github/ISSUE_TEMPLATE/config.yml"),
    DocumentSpec("pull_request_template", ".github/PULL_REQUEST_TEMPLATE.md"),
    DocumentSpec("pull_request_template", "PULL_REQUEST_TEMPLATE.md"),
)


def decode_document(content: ContentDTO) -> str:
    """Decode a GitHub base64 text document with explicit parse failures."""
    if content.content_type != "file":
        raise EntityParseError(f"repository content is not a file: {content.path}")
    if content.encoding != "base64" or content.content is None:
        raise EntityParseError(f"repository content is not base64 encoded: {content.path}")
    compact = "".join(content.content.split())
    try:
        decoded = base64.b64decode(compact, validate=True)
        return decoded.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        message = f"repository document is not valid UTF-8 base64: {content.path}"
        raise EntityParseError(message) from error
