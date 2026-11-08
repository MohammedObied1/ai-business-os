// Code 128 (set B, with set C for long digit runs) → bar widths. Any USB/Bluetooth barcode scanner reads it.
const P = ("212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 221312 231212 112232 122132 122231 113222 123122 123221 223211 221132 " +
  "221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 " +
  "231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 " +
  "314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 " +
  "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 " +
  "114131 311141 411131 211412 211214 211232 2331112").split(" ");
const START_B = 104, START_C = 105, CODE_B = 100, CODE_C = 99, STOP = 106;

export function code128(text: string): number[] {
  const values: number[] = [];
  const allDigits = /^\d+$/.test(text) && text.length % 2 === 0 && text.length >= 4;
  if (allDigits) {
    values.push(START_C);
    for (let i = 0; i < text.length; i += 2) values.push(+text.slice(i, i + 2));
  } else {
    values.push(START_B);
    let set: "B" | "C" = "B";
    let i = 0;
    while (i < text.length) {
      const run = /^\d+/.exec(text.slice(i))?.[0].length ?? 0;
      if (set === "B" && run >= 6) { values.push(CODE_C); set = "C"; }
      if (set === "C") {
        if ((/^\d+/.exec(text.slice(i))?.[0].length ?? 0) >= 2) { values.push(+text.slice(i, i + 2)); i += 2; continue; }
        values.push(CODE_B); set = "B";
      }
      const c = text.charCodeAt(i);
      values.push(c >= 32 && c < 128 ? c - 32 : 31); // unsupported characters print as "?"
      i++;
    }
  }
  const check = values.reduce((s, v, i) => s + v * (i === 0 ? 1 : i), 0) % 103;
  values.push(check, STOP);
  return values.flatMap((v) => P[v].split("").map(Number));
}

/** SVG markup: black bars on white with the text under them. */
export function code128Svg(text: string, height = 40, module = 1.4): string {
  const widths = code128(text);
  const quiet = 10;
  let x = quiet, bars = "";
  widths.forEach((w, i) => { if (i % 2 === 0) bars += `<rect x="${x * module}" y="0" width="${w * module}" height="${height}"/>`; x += w; });
  const total = (x + quiet) * module;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${height}" width="${total}" height="${height}" preserveAspectRatio="none">` +
    `<rect width="100%" height="100%" fill="#fff"/><g fill="#000">${bars}</g></svg>`;
}
