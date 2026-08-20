/** Client-side screenshot prep for /squad/extract. Vision models read shirt
 * labels fine at ~1200px, and phone screenshots are 3-4MB — downscaling here
 * keeps every upload far under the proxy's request-body limit. */

const MAX_DIM = 1200;
const JPEG_QUALITY = 0.85;

export async function fileToSquadImage(
  file: File,
): Promise<{ image: string; preview: string }> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error(`couldn't read “${file.name}” as an image — use a JPEG, PNG or WebP`);
  }
  const scale = Math.min(1, MAX_DIM / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas unavailable in this browser");
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const preview = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  return { image: preview.split(",", 2)[1], preview };
}
