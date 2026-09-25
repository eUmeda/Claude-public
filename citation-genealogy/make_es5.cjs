// index.html を「ES5 構文だけ・外部読み込みなし」の版に変換する（Culm の Cloudflare Pages へ置くため）。
// Culm リポジトリはフロントエンドを ES5・CDN なしに限っているので、ビューアのインラインスクリプトだけを
// Babel で ES5 に下げ、Google Fonts の読み込みを外す。データの JSON ブロックは触らない。
//
// 使い方:
//   (cd <作業用ディレクトリ> && npm i @babel/core @babel/preset-env)
//   NODE_PATH=<作業用ディレクトリ>/node_modules node make_es5.cjs index.html <出力先>/index.html
"use strict";
var fs = require("fs");
var babel = require("@babel/core");

var src = process.argv[2], out = process.argv[3];
if (!src || !out) { console.error("usage: node make_es5.cjs <in.html> <out.html>"); process.exit(2); }
var html = fs.readFileSync(src, "utf8");

// 1) 外部フォント（CDN）を外す。フォントは system-ui などの代替に落ちる
html = html.replace(/<link[^>]+fonts\.(googleapis|gstatic)\.com[^>]*>\s*/g, "");

var SCRIPT = /<script(?![^>]*\bsrc=)(?![^>]*type="application\/json")([^>]*)>([\s\S]*?)<\/script>/g;
// 2) インラインスクリプト（src なし・JSON でないもの）を ES5 へ
var n = 0;
html = html.replace(SCRIPT, function (all, attrs, code) {
  if (!code.trim()) return all;
  n++;
  var res = babel.transformSync(code, {
    presets: [["@babel/preset-env", { targets: "ie 11", modules: false }]],
    assumptions: { iterableIsArray: false, setSpreadProperties: true },
    sourceType: "script", babelrc: false, configFile: false, comments: false, compact: false,
  });
  return "<script" + attrs + ">\n" + res.code + "\n</script>";
});

// 3) 検査: 変換後のスクリプトに ES2015 以降の構文が残っていないこと（Culm の ES5 チェックと同じ正規表現＋テンプレート文字列）
var bad = [];
html.replace(SCRIPT, function (all, attrs, code) {
  code.split("\n").forEach(function (line, i) {
    if (/=>|\bconst\b|\blet\b|\bclass\s+[A-Z]|\bfetch\s*\(|`/.test(line)) bad.push(i + 1 + ": " + line.slice(0, 120));
  });
  return all;
});
if (/fonts\.googleapis|cdnjs|jsdelivr|unpkg/.test(html.replace(/<script id="graph-data"[\s\S]*?<\/script>/, ""))) bad.push("external reference remains");
if (bad.length) { console.error("ES5 check failed:\n" + bad.slice(0, 20).join("\n")); process.exit(1); }

fs.writeFileSync(out, html);
console.log("scripts transpiled: " + n + "  size: " + (Buffer.byteLength(html) / 1048576).toFixed(1) + " MB -> " + out);
