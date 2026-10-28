/* The window poster's QR code, apart from the kit's other helpers (lib/kit.ts) so its encoder is loaded with the poster
   alone, on the kit's page. */
import qrcode from "qrcode-generator";

/** A QR code as one SVG path of unit squares, with its size in modules; medium error correction survives a scuffed print. */
export function qrPath(text: string): { size: number; path: string } {
  const code = qrcode(0, "M");
  code.addData(text);
  code.make();
  const size = code.getModuleCount();
  const parts: string[] = [];
  for (let row = 0; row < size; row += 1) {
    for (let col = 0; col < size; col += 1) {
      if (code.isDark(row, col)) parts.push(`M${col} ${row}h1v1h-1z`);
    }
  }
  return { size, path: parts.join("") };
}
