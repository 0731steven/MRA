import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { normalizeMathMarkdown } from "../src/utils/mathMarkdown.ts";

const slash = "\\";
const inline = `行内公式 ${slash}(P(A${slash}mid B)${slash})`;
assert.equal(normalizeMathMarkdown(inline), `行内公式 $P(A${slash}mid B)$`);

const doubleEscaped = `题库公式 ${slash}${slash}(A_1${slash}${slash})`;
assert.equal(normalizeMathMarkdown(doubleEscaped), "题库公式 $A_1$");

const display = `推导如下：${slash}[${slash}frac{1}{2}${slash}]结束。`;
const normalizedDisplay = normalizeMathMarkdown(display);
assert.match(normalizedDisplay, /\$\$\s*\\frac\{1\}\{2\}\s*\$\$/);

const existing = `已有 $x^2$ 与 $$${slash}begin{matrix}a${slash}${slash}[4pt]b${slash}end{matrix}$$`;
assert.equal(
  normalizeMathMarkdown(existing),
  `已有 $x^2$ 与 \n\n$$\n${slash}begin{matrix}a${slash}${slash}[4pt]b${slash}end{matrix}\n$$\n\n`,
);

const malformedDisplay = `先验分布为$$\nP(${slash}lambda=1.5)=0.45\n$$\n继续计算。`;
const repairedDisplay = normalizeMathMarkdown(malformedDisplay);
assert.match(repairedDisplay, /先验分布为\n\n\$\$\nP\(\\lambda=1\.5\)=0\.45\n\$\$/);

const fenced = "```tex\n" + slash + "(x" + slash + ")\n```";
assert.equal(normalizeMathMarkdown(fenced), fenced);
const inlineCode = "`" + slash + "(x" + slash + ")`";
assert.equal(normalizeMathMarkdown(inlineCode), inlineCode);
const matrixSpacing = slash + slash + "[4pt]";
assert.equal(normalizeMathMarkdown(matrixSpacing), matrixSpacing);

const html = renderToStaticMarkup(
  React.createElement(
    ReactMarkdown,
    {
      remarkPlugins: [remarkGfm, remarkMath],
      rehypePlugins: [[rehypeKatex, { throwOnError: false, strict: "ignore", output: "htmlAndMathml" }]],
    },
    normalizeMathMarkdown(`${inline}\n\n${display}\n\n${malformedDisplay}`),
  ),
);
assert.match(html, /class="katex"/);
assert.doesNotMatch(html, /\\\(|\\\[|\\\]|\\\)/);
assert.doesNotMatch(html, /先验分布为\$\$/);

const tableHtml = renderToStaticMarkup(
  React.createElement(
    ReactMarkdown,
    { remarkPlugins: [remarkGfm, remarkMath] },
    "| 环节 | 时间 |\n| --- | --- |\n| 导入 | 5 分钟 |",
  ),
);
assert.match(tableHtml, /<table>/);
assert.match(tableHtml, /<th>环节<\/th>/);

assert.doesNotThrow(() => renderToStaticMarkup(
  React.createElement(
    ReactMarkdown,
    {
      remarkPlugins: [remarkGfm, remarkMath],
      rehypePlugins: [[rehypeKatex, { throwOnError: false, strict: "ignore" }]],
    },
    "$" + slash + "notARealCommand{x}$",
  ),
));

const bankPath = new URL("../../backend/data/probability_questions.jsonl", import.meta.url);
const bankRows = readFileSync(bankPath, "utf8").trim().split("\n").map(line => JSON.parse(line));
const legacyFields = bankRows.flatMap(row => [
  row.question,
  row.answer,
  row.explanation,
  ...(row.choices || []),
]).filter(value => typeof value === "string" && /\\{1,2}[([]/.test(value));

assert.ok(legacyFields.length > 0, "expected real question-bank legacy delimiters");
for (const source of legacyFields) {
  assert.doesNotThrow(() => renderToStaticMarkup(
    React.createElement(
      ReactMarkdown,
      {
        remarkPlugins: [remarkGfm, remarkMath],
        rehypePlugins: [[rehypeKatex, { throwOnError: false, strict: "ignore" }]],
      },
      normalizeMathMarkdown(source),
    ),
  ));
}

console.log(`math markdown rendering checks passed (${legacyFields.length} legacy corpus fields)`);
