import { EditorView, lineNumbers } from "@codemirror/view";
import { Compartment, EditorState } from "@codemirror/state";
import { oneDark } from "@codemirror/theme-one-dark";
import { StreamLanguage, syntaxHighlighting, HighlightStyle, defaultHighlightStyle } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { lua as luaLegacyMode } from "@codemirror/legacy-modes/mode/lua";
import { marked } from "marked";
import hljs from "highlight.js/lib/core";
import luaLang from "highlight.js/lib/languages/lua";

hljs.registerLanguage("lua", luaLang);

const lua = () => StreamLanguage.define(luaLegacyMode);

/** Подсветка Lua: контрастная, читаемая; акцент на ключевых словах и строках (MTS-стиль без кислотности). */
const mtsLuaHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#6a1b9a", fontWeight: "600" },
  { tag: tags.operator, color: "#3949ab" },
  { tag: tags.number, color: "#00695c" },
  { tag: tags.string, color: "#c62828" },
  { tag: tags.comment, color: "#616161", fontStyle: "italic" },
  { tag: tags.variableName, color: "#1565c0" },
  { tag: tags.propertyName, color: "#0d47a1" },
  { tag: tags.definition(tags.variableName), color: "#1565c0", fontWeight: "500" },
  { tag: tags.atom, color: "#5d4037" },
  { tag: tags.bool, color: "#6a1b9a" },
  { tag: tags.meta, color: "#757575" },
  { tag: tags.invalid, color: "#b71c1c", fontWeight: "600" },
]);

export {
  Compartment,
  EditorState,
  EditorView,
  defaultHighlightStyle,
  hljs,
  lineNumbers,
  lua,
  marked,
  mtsLuaHighlight,
  oneDark,
  syntaxHighlighting,
};
