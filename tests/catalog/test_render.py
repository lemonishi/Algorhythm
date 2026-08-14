from algorhythm.catalog.render import render_statement


def test_paragraphs_are_separated_by_blank_lines():
    out = render_statement("<p>First.</p><p>Second.</p>")
    assert out == "First.\n\nSecond."


def test_inline_code_becomes_backticks():
    out = render_statement("<p>Return <code>root</code> now.</p>")
    assert out == "Return `root` now."


def test_strong_becomes_bold():
    assert render_statement("<p><strong>Note:</strong> x</p>") == "**Note:** x"


def test_emphasis_becomes_italics():
    assert render_statement("<p><em>the answer</em></p>") == "*the answer*"


def test_pre_blocks_become_fenced_code():
    out = render_statement("<pre>Input: root = [1]\nOutput: [[1]]\n</pre>")
    assert out == "```\nInput: root = [1]\nOutput: [[1]]\n```"


def test_tags_inside_pre_are_stripped_not_rendered():
    out = render_statement("<pre><strong>Input:</strong> x = 1\n</pre>")
    assert out == "```\nInput: x = 1\n```"


def test_list_items_become_dashes():
    out = render_statement("<ul><li>one</li><li>two</li></ul>")
    assert out == "- one\n- two"


def test_html_entities_are_unescaped():
    assert render_statement("<p>-1000 &lt;= x &lt;= 1000</p>") == "-1000 <= x <= 1000"


def test_nbsp_becomes_a_plain_space():
    assert render_statement("<p>a&nbsp;b</p>") == "a b"


def test_superscript_becomes_caret():
    assert render_statement("<p>10<sup>4</sup></p>") == "10^4"


def test_images_are_kept_as_markdown_references():
    out = render_statement('<p><img alt="tree" src="https://x/y.jpg" /></p>')
    assert out == "![tree](https://x/y.jpg)"


def test_images_without_alt_text_still_render():
    out = render_statement('<p><img src="https://x/y.jpg" /></p>')
    assert out == "![](https://x/y.jpg)"


def test_leading_and_trailing_whitespace_is_trimmed():
    assert render_statement("\n\n<p>  hi  </p>\n\n") == "hi"


def test_empty_input_gives_empty_output():
    assert render_statement("") == ""


def test_pre_blocks_preserve_internal_blank_lines():
    out = render_statement("<pre>a\n\n\nb</pre>")
    assert out == "```\na\n\n\nb\n```"


def test_unclosed_pre_still_renders_its_body():
    out = render_statement("<p>before</p><pre>Input: [1]")
    assert out == "before\n\n```\nInput: [1]\n```"


def test_self_closing_br_matches_open_close_br():
    assert render_statement("<p>a<br/>b</p>") == render_statement("<p>a<br>b</p>")
