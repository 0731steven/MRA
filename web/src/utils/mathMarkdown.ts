const protectedCode = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`+[^`\n]*`+)/g;
const protectedMath = /(\$\$[\s\S]*?\$\$|\$(?:\\.|[^$\n])+\$)/g;

/**
 * Display math is only recognized reliably when both `$$` fences own a line.
 * Imported documents and model output often attach the opener to prose, for
 * example `先验分布为$$\n...\n$$`. Canonicalize every complete display span
 * before remark-math sees it. Code remains protected by the outer split.
 */
function normalizeDisplayMath(segment: string): string {
  return segment.replace(/\$\$([\s\S]*?)\$\$/g, (match, body: string) => {
    const formula = body.trim();
    if (!formula) return match;
    return `\n\n$$\n${formula}\n$$\n\n`;
  });
}

function normalizePlainText(segment: string): string {
  return segment
    .replace(/(\\+)\(/g, (match, slashes: string) => slashes.length <= 2 ? "$" : match)
    .replace(/(\\+)\)/g, (match, slashes: string) => slashes.length <= 2 ? "$" : match)
    .replace(
      /(\\+)\[(?!\s*[-+]?(?:\d*\.?\d+)(?:pt|em|ex|mu|mm|cm|in)\s*\])/g,
      (match, slashes: string) => slashes.length <= 2 ? "\n\n$$\n" : match,
    )
    .replace(/(\\+)\]/g, (match, slashes: string) => slashes.length <= 2 ? "\n$$\n\n" : match);
}

/**
 * Normalize common model/document math delimiters to remark-math syntax.
 *
 * Fenced code, inline code and inline dollar math stay byte-for-byte intact.
 * Complete display-dollar spans are moved onto their own lines. This is also
 * important for matrix line breaks such as `\\\\[4pt]`, which must never be
 * mistaken for a display-math opener.
 */
export function normalizeMathMarkdown(markdown: string): string {
  if (!markdown) return "";
  return markdown
    .split(protectedCode)
    .map((codeSegment, codeIndex) => {
      if (codeIndex % 2 === 1) return codeSegment;
      return normalizeDisplayMath(codeSegment)
        .split(protectedMath)
        .map((segment, mathIndex) => mathIndex % 2 === 1 ? segment : normalizePlainText(segment))
        .join("");
    })
    .join("");
}
