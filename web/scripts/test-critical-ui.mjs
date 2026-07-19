import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const tutor = readFileSync(new URL("../src/pages/TutorPage.tsx", import.meta.url), "utf8");
const questionBank = readFileSync(new URL("../src/pages/QuestionBankPage.tsx", import.meta.url), "utf8");
const auth = readFileSync(new URL("../src/contexts/AuthContext.tsx", import.meta.url), "utf8");
const main = readFileSync(new URL("../src/main.tsx", import.meta.url), "utf8");

assert.doesNotMatch(
  tutor,
  /useEffect\(\(\)\s*=>\s*bottom\.current\?\.scrollIntoView/,
  "scroll effect must not return the scrollIntoView result",
);
assert.match(tutor, /useEffect\(\(\)\s*=>\s*\{[\s\S]*?bottom\.current\?\.scrollIntoView/);
assert.match(tutor, /credentials:\s*"same-origin"/);
assert.match(questionBank, /questions\/\$\{selected\.ID\}\/answer/);
assert.doesNotMatch(auth, /localStorage\.setItem\("token"/);
assert.match(main, /@ant-design\/v5-patch-for-react-19/);

console.log("critical UI regression checks passed");
