"""Re-encode SCREENSHOT_*.png in AllTestRuns/ to WebP, in place.

The uploader publishes WebP now (~22x smaller than the Quest PNG, alpha intact);
this catches up the runs published before that. Both dashboards read either
extension, so a partly-converted tree renders fine. Full-size PNGs stay on Drive.

    python .github/scripts/recompress_screenshots.py --dry-run
    python .github/scripts/recompress_screenshots.py
"""

import argparse
import glob
import io
import os
import sys

QUALITY = 85


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report sizes without touching files")
    parser.add_argument("--quality", type=int, default=QUALITY)
    args = parser.parse_args()

    from PIL import Image

    pngs = sorted(glob.glob(os.path.join("AllTestRuns", "*", "SCREENSHOT_*.png")))
    if not pngs:
        print("No PNG screenshots found — nothing to do.")
        return 0

    before = after = 0
    failed = 0
    for path in pngs:
        src_size = os.path.getsize(path)
        webp_path = os.path.splitext(path)[0] + ".webp"
        try:
            buf = io.BytesIO()
            Image.open(path).save(buf, "WEBP", quality=args.quality, method=4)
            data = buf.getvalue()
        except Exception as e:
            print(f"  FAILED {path}: {e}")
            failed += 1
            continue

        before += src_size
        after += len(data)
        print(f"  {src_size // 1024:>5} KB -> {len(data) // 1024:>4} KB  {os.path.basename(os.path.dirname(path))}/{os.path.basename(path)}")

        if args.dry_run:
            continue
        with open(webp_path, "wb") as f:
            f.write(data)
        os.remove(path)

    verb = "would save" if args.dry_run else "saved"
    print(f"\n{len(pngs) - failed} screenshot(s): {before / 1048576:.0f} MB -> {after / 1048576:.0f} MB "
          f"({verb} {(before - after) / 1048576:.0f} MB)")
    if failed:
        print(f"{failed} file(s) failed and were left as PNG.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
