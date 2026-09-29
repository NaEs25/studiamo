"""
Study Studio heading buttons: pressing the active heading again returns to a paragraph, and a
heading applied inside a bullet list takes that item out of the list instead of wrapping the
list in another heading on every press.

Drives the real toolbar buttons on the real editor. No video is open, so there is nothing to
save, and any /api/videos POST is intercepted regardless.
"""


def _open_editor(page, html):
    page.route("**/api/videos/**", lambda route: route.fulfill(status=200, content_type="application/json", body="{}")
               if route.request.method == "POST" else route.continue_())
    page.goto("/app")
    page.wait_for_selector("#nav-dashboard", timeout=15000)
    page.evaluate("""html => {
        document.getElementById('overlay-study-studio').classList.remove('hidden');
        document.getElementById('studio-notes-editor').innerHTML = html;
    }""", html)


def _caret_into(page, selector):
    page.evaluate("""sel => {
        const editor = document.getElementById('studio-notes-editor');
        editor.focus();
        const target = editor.querySelector(sel);
        const text = document.createTreeWalker(target, NodeFilter.SHOW_TEXT).nextNode();
        const range = document.createRange();
        range.setStart(text, 1);
        range.collapse(true);
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
    }""", selector)


def _button(page, label):
    return page.locator("#studio-toolbar-buttons button", has_text=label)


def _editor_html(page):
    return page.inner_html("#studio-notes-editor")


def test_heading_button_toggles_back_to_paragraph(logged_in_page):
    page = logged_in_page
    _open_editor(page, "<p>hello world</p>")

    _caret_into(page, "p")
    _button(page, "H1").click()
    assert _editor_html(page) == "<h1>hello world</h1>"

    _caret_into(page, "h1")
    _button(page, "H1").click()
    assert _editor_html(page) == "<p>hello world</p>"

    _caret_into(page, "p")
    _button(page, "H2").click()
    _caret_into(page, "h2")
    _button(page, "H1").click()
    assert _editor_html(page) == "<h1>hello world</h1>"


def test_heading_inside_a_list_does_not_nest(logged_in_page):
    page = logged_in_page
    _open_editor(page, "<ul><li>one</li><li>two</li></ul>")

    _caret_into(page, "li")
    _button(page, "H2").click()
    assert _editor_html(page) == "<h2>one</h2><ul><li>two</li></ul>"

    _caret_into(page, "h2")
    _button(page, "H2").click()
    assert _editor_html(page) == "<p>one</p><ul><li>two</li></ul>"
    assert "<h2><h2>" not in _editor_html(page)
