"""A dependency-free DOM renderer for packaged TrainLab email designs.

Inputs are represented as a deliberately small HTML tree.  Plain strings are
always serialized as escaped text.  Markup can only enter a repeat through an
``Element`` or ``Text`` node explicitly constructed by the trusted caller.
"""

from __future__ import annotations

from copy import deepcopy
from html import escape
from html.parser import HTMLParser
from importlib.resources import files
from typing import Iterable, Mapping, Sequence


_TEMPLATE_FILES = {
    "daily_report": "daily_report.html",
    "weekly_report": "weekly_report.html",
    "mail_reply": "mail_reply.html",
}
_BINDING_ATTRIBUTES = frozenset(
    {"data-field", "data-repeat", "data-optional", "data-variant", "data-od-id"}
)
_UNRESOLVED_ATTRIBUTES = _BINDING_ATTRIBUTES - {"data-od-id"}
_VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


class EmailTemplateError(ValueError):
    """Raised when a template cannot be safely rendered to a final email."""


class Text:
    """Trusted text node; its content is escaped during serialization."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("text_value_must_be_string")
        self.value = value


class _Comment:
    """A parser-only static design comment, never constructable by callers."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class Element:
    """A small, caller-constructable HTML element for trusted repeat content."""

    __slots__ = ("tag", "attributes", "children")

    def __init__(
        self,
        tag: str,
        children: Iterable[Element | Text] = (),
        *,
        attributes: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(tag, str) or not tag or not tag.replace("-", "a").isalnum():
            raise ValueError("element_tag_invalid")
        self.tag = tag.lower()
        self.attributes = list((attributes or {}).items())
        self.children = list(children)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.attributes):
            raise TypeError("element_attributes_must_map_strings_to_strings")
        if not all(isinstance(child, (Element, Text)) for child in self.children):
            raise TypeError("element_children_must_be_nodes")

    def clone(self) -> Element:
        """Return an independent copy suitable for a new repeat item."""
        return deepcopy(self)

    def attribute_values(self, name: str) -> tuple[str, ...]:
        return tuple(value for key, value in self.attributes if key == name)

    def discard_attribute(self, name: str) -> None:
        self.attributes = [(key, value) for key, value in self.attributes if key != name]


def text(value: str) -> Text:
    """Construct a trusted text node (still escaped when rendered)."""
    return Text(value)


def element(
    tag: str,
    *children: Element | Text,
    attributes: Mapping[str, str] | None = None,
) -> Element:
    """Construct trusted repeat markup without accepting raw HTML strings."""
    return Element(tag, children, attributes=attributes)


class _TemplateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.declarations: list[str] = []

    def handle_decl(self, decl: str) -> None:
        self.declarations.append(f"<!{decl}>")

    def handle_comment(self, data: str) -> None:
        self.stack[-1].children.append(_Comment(data))  # type: ignore[arg-type]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Element(tag, attributes={})
        node.attributes = [(name, "" if value is None else value) for name, value in attrs]
        self.stack[-1].children.append(node)
        if tag.lower() not in _VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag.lower():
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(Text(data))


def _serialize(node: Element | Text | _Comment) -> str:
    if isinstance(node, _Comment):
        return f"<!--{node.value}-->"
    if isinstance(node, Text):
        return escape(node.value, quote=False)
    if node.tag == "document":
        return "".join(_serialize(child) for child in node.children)
    attrs = "".join(f' {key}="{escape(value, quote=True)}"' for key, value in node.attributes)
    if node.tag in _VOID_ELEMENTS:
        return f"<{node.tag}{attrs}>"
    return f"<{node.tag}{attrs}>" + "".join(_serialize(child) for child in node.children) + f"</{node.tag}>"


def _walk(node: Element) -> Iterable[Element]:
    for child in node.children:
        if isinstance(child, Element):
            yield child
            yield from _walk(child)


def _nodes_including(root: Element) -> Iterable[Element]:
    yield root
    yield from _walk(root)


def _string_mapping(values: Mapping[str, str], *, label: str) -> None:
    if not isinstance(values, Mapping) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in values.items()):
        raise TypeError(f"{label}_must_map_strings_to_strings")


def _is_empty(value: object) -> bool:
    return value is None or value is False or value == "" or (hasattr(value, "__len__") and len(value) == 0)


class Template:
    """Mutable parsed template with explicit binding-resolution operations."""

    def __init__(self, root: Element, declarations: Sequence[str] = ()) -> None:
        self.root = root
        self.declarations = tuple(declarations)

    def clone(self) -> Template:
        return Template(self.root.clone(), self.declarations)

    def set_fields(self, values: Mapping[str, str]) -> Template:
        """Replace every matching ``data-field`` with escaped plain text."""
        _string_mapping(values, label="field_values")
        for node in _nodes_including(self.root):
            names = node.attribute_values("data-field")
            matched = next((name for name in reversed(names) if name in values), None)
            if matched is not None:
                node.children = [Text(values[matched])]
                node.discard_attribute("data-field")
        return self

    def remove_empty_optional(self, values: Mapping[str, object]) -> Template:
        """Delete optional nodes with empty values and resolve surviving markers."""
        if not isinstance(values, Mapping) or any(not isinstance(key, str) for key in values):
            raise TypeError("optional_values_must_map_string_keys")

        def visit(parent: Element) -> None:
            kept: list[Element | Text] = []
            for child in parent.children:
                if not isinstance(child, Element):
                    kept.append(child)
                    continue
                names = child.attribute_values("data-optional")
                if names and any(_is_empty(values.get(name)) for name in names):
                    continue
                child.discard_attribute("data-optional")
                visit(child)
                kept.append(child)
            parent.children = kept

        visit(self.root)
        return self

    def replace_repeats(self, values: Mapping[str, Sequence[str | Element | Text]]) -> Template:
        """Replace repeat-container content with escaped text or trusted nodes."""
        if not isinstance(values, Mapping) or any(not isinstance(key, str) for key in values):
            raise TypeError("repeat_values_must_map_string_keys")
        for node in _nodes_including(self.root):
            names = node.attribute_values("data-repeat")
            matched = next((name for name in reversed(names) if name in values), None)
            if matched is None:
                continue
            items = values[matched]
            if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
                raise TypeError("repeat_value_must_be_a_sequence")
            children: list[Element | Text] = []
            for item in items:
                if isinstance(item, str):
                    children.append(Text(item))
                elif isinstance(item, (Element, Text)):
                    children.append(deepcopy(item))
                else:
                    raise TypeError("repeat_items_must_be_strings_or_nodes")
            node.children = children
            node.discard_attribute("data-repeat")
        return self

    def select_variant(self, variant: str) -> Template:
        """Keep only children marked with ``variant`` and resolve their markers.

        Apply this to a cloned structural fragment (usually a repeat item), not
        the whole weekly template when each item can choose independently.
        """
        if not isinstance(variant, str) or not variant:
            raise ValueError("variant_invalid")

        def visit(parent: Element) -> None:
            kept: list[Element | Text] = []
            for child in parent.children:
                if not isinstance(child, Element):
                    kept.append(child)
                    continue
                names = child.attribute_values("data-variant")
                if names and variant not in names:
                    continue
                child.discard_attribute("data-variant")
                visit(child)
                kept.append(child)
            parent.children = kept

        visit(self.root)
        return self

    def finalize(self) -> str:
        """Reject unresolved bindings, strip design IDs, and serialize HTML."""
        assert_no_bindings(self.root)
        for node in _nodes_including(self.root):
            node.discard_attribute("data-od-id")
        return "".join(self.declarations) + _serialize(self.root)


def clone_variant(fragment: Template | Element, variant: str) -> Template | Element:
    """Clone a fragment and retain its requested structural variant."""
    if isinstance(fragment, Template):
        return fragment.clone().select_variant(variant)
    if isinstance(fragment, Element):
        root = fragment.clone()
        names = root.attribute_values("data-variant")
        if names and variant not in names:
            raise EmailTemplateError("requested_variant_not_present")
        root.discard_attribute("data-variant")
        template = Template(root).select_variant(variant)
        return template.root
    raise TypeError("fragment_must_be_template_or_element")


def assert_no_bindings(root: Element) -> None:
    """Raise unless all field/repeat/optional/variant markers were resolved."""
    unresolved = sorted(
        {attribute for node in _nodes_including(root) for attribute, _ in node.attributes if attribute in _UNRESOLVED_ATTRIBUTES}
    )
    if unresolved:
        raise EmailTemplateError("unresolved_template_bindings:" + ",".join(unresolved))


def load_template(email_type: str) -> Template:
    """Load one of the packaged design sources by stable email type."""
    try:
        filename = _TEMPLATE_FILES[email_type]
    except (KeyError, TypeError) as exc:
        raise EmailTemplateError("unknown_email_template") from exc
    source = files("trainlab.email_templates.templates").joinpath(filename).read_text(encoding="utf-8")
    parser = _TemplateParser()
    parser.feed(source)
    parser.close()
    return Template(parser.root, parser.declarations)


def render_template(
    email_type: str,
    *,
    fields: Mapping[str, str],
    optional: Mapping[str, object],
    repeats: Mapping[str, Sequence[str | Element | Text]],
    variant: str | None = None,
) -> str:
    """Convenience rendering pipeline for a fully resolved email template."""
    template = load_template(email_type)
    if variant is not None:
        template.select_variant(variant)
    template.remove_empty_optional(optional).replace_repeats(repeats).set_fields(fields)
    return template.finalize()
