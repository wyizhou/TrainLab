"""Safe, deterministic HTML email-template primitives.

The package deliberately has no knowledge of delivery, payload validation, or
business policy.  Both production chains can load a packaged design and apply
only the already-approved visible values through this small DOM API.
"""

from .rendering import (
    EmailTemplateError,
    Element,
    Template,
    Text,
    assert_no_bindings,
    clone_variant,
    element,
    load_template,
    render_template,
    text,
)

__all__ = [
    "EmailTemplateError",
    "Element",
    "Template",
    "Text",
    "assert_no_bindings",
    "clone_variant",
    "element",
    "load_template",
    "render_template",
    "text",
]
