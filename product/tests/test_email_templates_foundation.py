from trainlab.email_templates import (
    EmailTemplateError,
    assert_no_bindings,
    element,
    load_template,
    render_template,
    text,
)


def test_packaged_template_resources_load() -> None:
    for email_type in ("daily_report", "weekly_report", "mail_reply"):
        assert any(node.attribute_values("data-field") for node in _walk_elements(load_template(email_type).root))


def test_field_content_is_escaped_and_template_example_is_replaced() -> None:
    html = _render_daily(title="<script>alert('no')</script>")
    assert "&lt;script&gt;alert('no')&lt;/script&gt;" in html
    assert "<script>alert('no')</script>" not in html
    assert ">每日训练简报</h1>" not in html
    assert ">Hansons 轻松跑<" not in html
    assert ">Hansons Marathon Method<" not in _render_complete("weekly_report")
    assert ">收到你的来信<" not in _render_complete("mail_reply")


def test_repeat_text_is_escaped_and_empty_optional_block_is_deleted() -> None:
    html = _render_daily(optional={"decision_factors": []}, repeats={"decision_factors": ["<unsafe>"]})
    assert "判断依据" not in html
    assert "&lt;unsafe&gt;" not in html


def test_finalization_cleans_all_design_attributes_and_rejects_unresolved() -> None:
    template = load_template("mail_reply")
    try:
        template.finalize()
    except EmailTemplateError:
        pass
    else:
        raise AssertionError("unresolved bindings must be rejected")

    node = element("div", text("ok"), attributes={"data-od-id": "design"})
    assert_no_bindings(node)
    template = load_template("mail_reply")
    template.root.children = [node]
    assert 'data-od-id' not in template.finalize()
    html = _render_daily()
    for attribute in ("data-field", "data-repeat", "data-optional", "data-variant", "data-od-id"):
        assert attribute not in html


def _walk_elements(root):
    for child in root.children:
        if hasattr(child, "children"):
            yield child
            yield from _walk_elements(child)


def _render_daily(*, title="safe title", optional=None, repeats=None) -> str:
    return _render_complete("daily_report", title=title, optional=optional, repeats=repeats)


def _render_complete(email_type, *, title="safe title", optional=None, repeats=None) -> str:
    template = load_template(email_type)
    fields = {
        name: title if name == "title" else f"value:{name}"
        for node in _walk_elements(template.root)
        for name in node.attribute_values("data-field")
    }
    optional_values = {
        name: True
        for node in _walk_elements(template.root)
        for name in node.attribute_values("data-optional")
    }
    repeat_values = {
        name: [f"repeat:{name}"]
        for node in _walk_elements(template.root)
        for name in node.attribute_values("data-repeat")
    }
    optional_values.update(optional or {})
    repeat_values.update(repeats or {})
    variant = "running" if any(node.attribute_values("data-variant") for node in _walk_elements(template.root)) else None
    return render_template(email_type, fields=fields, optional=optional_values, repeats=repeat_values, variant=variant)
