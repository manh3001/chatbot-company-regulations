const test = require("node:test");
const assert = require("node:assert/strict");
const { escapeHtml, renderMarkdown, parseCitation } = require("../../static/lib.js");

test("escapeHtml neutralizes HTML", () => {
  assert.equal(
    escapeHtml('<script>"x"&\'</script>'),
    "&lt;script&gt;&quot;x&quot;&amp;&#39;&lt;/script&gt;"
  );
});

test("renderMarkdown escapes before transforming", () => {
  const html = renderMarkdown("<b>hi</b>");
  assert.ok(html.includes("&lt;b&gt;hi&lt;/b&gt;"));
  assert.ok(!html.includes("<b>hi</b>"));
});

test("renderMarkdown handles bold, italic, and inline code", () => {
  assert.ok(renderMarkdown("**bold**").includes("<strong>bold</strong>"));
  assert.ok(renderMarkdown("*it*").includes("<em>it</em>"));
  assert.ok(renderMarkdown("`code`").includes("<code>code</code>"));
});

test("renderMarkdown builds an unordered list", () => {
  const html = renderMarkdown("- a\n- b");
  assert.ok(html.includes("<ul>"));
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.ok(html.includes("</ul>"));
});

test("renderMarkdown builds an ordered list", () => {
  const html = renderMarkdown("1. a\n2. b");
  assert.ok(html.includes("<ol>"));
  assert.ok(html.includes("</ol>"));
});

test("renderMarkdown renders headings", () => {
  assert.ok(renderMarkdown("## Title").includes("<h2>Title</h2>"));
});

test("parseCitation splits off a trailing Nguồn line", () => {
  const { answer, source } = parseCitation(
    "Giờ làm việc là 8h.\nNguồn: Mục 2. Thời gian làm việc"
  );
  assert.equal(answer, "Giờ làm việc là 8h.");
  assert.equal(source, "Mục 2. Thời gian làm việc");
});

test("parseCitation returns null source when absent", () => {
  const { answer, source } = parseCitation("Không có thông tin trong nội quy.");
  assert.equal(answer, "Không có thông tin trong nội quy.");
  assert.equal(source, null);
});

test("parseCitation ignores trailing blank lines after the source", () => {
  const { source } = parseCitation("Trả lời.\nNguồn: Mục 1\n\n");
  assert.equal(source, "Mục 1");
});
