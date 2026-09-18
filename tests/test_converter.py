from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from converter import (
    IMAGE_OUTPUT_FORMATS,
    IMAGE_FORMAT_CAPABILITIES,
    SUPPORTED_EXTENSIONS,
    apply_image_transformations,
    convert_image,
    estimate_image_output_size,
)
from utils import (
    export_results_to_csv,
    format_saved_percentage,
    format_file_size,
    next_available_output_path,
    scan_directory_for_images,
)


class ConverterTests(unittest.TestCase):
    def test_every_output_format_has_capability_metadata(self) -> None:
        self.assertEqual(set(IMAGE_OUTPUT_FORMATS), set(IMAGE_FORMAT_CAPABILITIES))
        for format_name, metadata in IMAGE_FORMAT_CAPABILITIES.items():
            self.assertTrue(metadata["category"], format_name)
            self.assertTrue(metadata["description"], format_name)
            self.assertTrue(metadata["badges"], format_name)

    def test_preserves_grayscale_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "alpha.png"
            Image.new("LA", (12, 8), (180, 73)).save(source)

            result = convert_image(source, root / "output", 80)

            self.assertEqual(result.status, "Completed")
            self.assertIsNotNone(result.output_path)
            with Image.open(result.output_path) as converted:
                self.assertEqual(converted.mode, "RGBA")
                self.assertEqual(converted.getpixel((0, 0))[3], 73)

    def test_applies_exif_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "oriented.jpg"
            image = Image.new("RGB", (20, 10), "white")
            ImageDraw.Draw(image).rectangle((0, 0, 4, 9), fill="red")
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)

            result = convert_image(source, root / "output", 80)

            self.assertEqual(result.status, "Completed")
            self.assertIsNotNone(result.output_path)
            with Image.open(result.output_path) as converted:
                self.assertEqual(converted.size, (10, 20))
                self.assertGreater(converted.getpixel((2, 2))[0], 200)

    def test_reserves_same_named_outputs_when_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one" / "photo.jpg"
            second = root / "two" / "photo.png"
            third = root / "three" / "photo.bmp"
            first.parent.mkdir()
            second.parent.mkdir()
            third.parent.mkdir()
            Image.new("RGB", (8, 8), "red").save(first)
            Image.new("RGB", (8, 8), "blue").save(second)
            Image.new("RGB", (8, 8), "green").save(third)
            output = root / "output"
            reserved: set[Path] = set()

            first_result = convert_image(first, output, 80, True, reserved)
            second_result = convert_image(second, output, 80, True, reserved)
            third_result = convert_image(third, output, 80, True, reserved)

            self.assertEqual(first_result.output_path.name, "photo.webp")
            self.assertEqual(second_result.output_path.name, "photo_1.webp")
            self.assertEqual(third_result.output_path.name, "photo_2.webp")

    def test_reports_files_that_are_larger(self) -> None:
        self.assertEqual(format_saved_percentage(100, 120), "20.0% larger")

    def test_next_available_output_path_uses_safe_default_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "report.pdf"

            result = next_available_output_path(target)

            self.assertEqual(result, target)
            self.assertFalse(result.exists())

    def test_preserves_exif_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "metadata.jpg"
            image = Image.new("RGB", (12, 8), "green")
            exif = image.getexif()
            exif[315] = "WebP Compressor Test"
            image.save(source, exif=exif)

            result = convert_image(source, root / "output", 80, preserve_metadata=True)

            self.assertEqual(result.status, "Completed")
            self.assertIsNotNone(result.output_path)
            with Image.open(result.output_path) as converted:
                self.assertEqual(converted.getexif().get(315), "WebP Compressor Test")

    def test_all_supported_input_formats(self) -> None:
        """Test representative files from every supported image family."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            cases = {
                ".jpg": "JPEG",
                ".jfif": "JPEG",
                ".png": "PNG",
                ".bmp": "BMP",
                ".tiff": "TIFF",
                ".webp": "WEBP",
                ".avif": "AVIF",
                ".heic": "HEIF",
                ".gif": "GIF",
                ".jp2": "JPEG2000",
                ".dds": "DDS",
                ".tga": "TGA",
                ".qoi": "QOI",
                ".pcx": "PCX",
                ".ppm": "PPM",
                ".sgi": "SGI",
                ".xbm": "XBM",
                ".im": "IM",
                ".msp": "MSP",
                ".ico": "ICO",
                ".icns": "ICNS",
            }
            for ext, source_format in cases.items():
                source = root / f"sample{ext}"
                image = Image.new("RGB", (32, 32), (100, 150, 200))
                if source_format in ("XBM", "MSP"):
                    image = image.convert("1")
                image.save(source, format=source_format)
                result = convert_image(source, output, 80)
                self.assertEqual(result.status, "Completed", f"Failed for format {ext}: {result.error}")
                self.assertTrue(result.output_path.exists())
                self.assertEqual(result.output_path.suffix.lower(), ".webp")
                with Image.open(result.output_path) as converted:
                    expected_size = (1024, 1024) if source_format == "ICNS" else (32, 32)
                    self.assertEqual(converted.size, expected_size)

    def test_all_supported_output_formats(self) -> None:
        """Every output choice should create a file using its advertised encoder."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            Image.new("RGBA", (300, 200), (100, 150, 200, 128)).save(source)

            for target_format, (expected_ext, _encoder) in IMAGE_OUTPUT_FORMATS.items():
                result = convert_image(
                    source,
                    root / target_format.replace(" ", "_"),
                    quality=80,
                    target_format=target_format,
                )
                self.assertEqual(
                    result.status,
                    "Completed",
                    f"Failed for output {target_format}: {result.error}",
                )
                self.assertIsNotNone(result.output_path)
                self.assertEqual(result.output_path.suffix.lower(), expected_ext)
                self.assertTrue(result.output_path.is_file())
                self.assertGreater(result.output_path.stat().st_size, 0)

    def test_output_size_estimate_matches_real_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            Image.new("RGB", (96, 64), (50, 100, 150)).save(source)

            estimated = estimate_image_output_size(
                source,
                quality=73,
                target_format="WEBP",
                max_width=48,
                max_height=48,
            )
            actual = convert_image(
                source,
                root / "actual",
                quality=73,
                target_format="WEBP",
                max_width=48,
                max_height=48,
            )

            self.assertEqual(actual.status, "Completed", actual.error)
            self.assertEqual(estimated, actual.output_size)

    def test_animated_input_to_gif_preserves_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "animated.webp"
            frames = [
                Image.new("RGBA", (24, 16), "red"),
                Image.new("RGBA", (24, 16), "blue"),
            ]
            frames[0].save(
                source,
                format="WEBP",
                save_all=True,
                append_images=frames[1:],
                duration=[100, 200],
                loop=0,
            )

            result = convert_image(source, root / "out", target_format="GIF")

            self.assertEqual(result.status, "Completed", result.error)
            with Image.open(result.output_path) as converted:
                self.assertTrue(converted.is_animated)
                self.assertEqual(converted.n_frames, 2)

    def test_png_transparency(self) -> None:
        """Verify RGBA transparency and palette transparency are preserved."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"

            # RGBA PNG with semi-transparent pixels
            rgba_path = root / "transparent.png"
            rgba_img = Image.new("RGBA", (16, 16), (255, 0, 0, 128))
            rgba_img.save(rgba_path)

            result = convert_image(rgba_path, output, 80)
            self.assertEqual(result.status, "Completed")
            with Image.open(result.output_path) as converted:
                self.assertEqual(converted.mode, "RGBA")
                pixel = converted.getpixel((8, 8))
                self.assertEqual(len(pixel), 4)
                self.assertGreater(pixel[3], 100)
                self.assertLess(pixel[3], 160)

            # Palette P mode with transparency
            p_path = root / "palette_trans.png"
            p_img = Image.new("P", (16, 16))
            p_img.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
            p_img.info["transparency"] = 0
            p_img.save(p_path)

            result_p = convert_image(p_path, output, 80)
            self.assertEqual(result_p.status, "Completed")
            with Image.open(result_p.output_path) as converted:
                self.assertEqual(converted.mode, "RGBA")

    def test_quality_values_20_50_80_100(self) -> None:
        """Verify quality settings 20, 50, 80, 100 produce valid outputs with progressive sizes."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Create a rich natural-like image to see compression differences
            source = root / "rich_photo.png"
            img = Image.new("RGB", (128, 128))
            draw = ImageDraw.Draw(img)
            for i in range(128):
                draw.line([(0, i), (127, i)], fill=(i * 2 % 256, (i * 3) % 256, (i * 5) % 256))
            img.save(source)

            sizes: dict[int, int] = {}
            for q in (20, 50, 80, 100):
                out_dir = root / f"out_{q}"
                res = convert_image(source, out_dir, q)
                self.assertEqual(res.status, "Completed")
                self.assertIsNotNone(res.output_size)
                sizes[q] = res.output_size
                with Image.open(res.output_path) as converted:
                    self.assertEqual(converted.size, (128, 128))

            # Quality 20 should produce smaller output than quality 100
            self.assertLess(sizes[20], sizes[80])
            self.assertLess(sizes[80], sizes[100])

    def test_existing_output_files_without_overwrite(self) -> None:
        """When overwrite=False, generates numbered files photo_1.webp, photo_2.webp."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            # Pre-existing file
            existing = output / "sample.webp"
            existing.write_text("existing")

            source = root / "sample.png"
            Image.new("RGB", (16, 16), "blue").save(source)

            res1 = convert_image(source, output, 80, overwrite=False)
            self.assertEqual(res1.status, "Completed")
            self.assertEqual(res1.output_path.name, "sample_1.webp")
            self.assertEqual(existing.read_text(), "existing")

            res2 = convert_image(source, output, 80, overwrite=False)
            self.assertEqual(res2.status, "Completed")
            self.assertEqual(res2.output_path.name, "sample_2.webp")

    def test_existing_output_files_with_overwrite(self) -> None:
        """When overwrite=True, replaces existing output file."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            target = output / "sample.webp"
            target.write_bytes(b"old-content-placeholder")

            source = root / "sample.png"
            Image.new("RGB", (16, 16), "yellow").save(source)

            res = convert_image(source, output, 80, overwrite=True)
            self.assertEqual(res.status, "Completed")
            self.assertEqual(res.output_path.name, "sample.webp")
            # Must have overwritten with valid WebP
            with Image.open(res.output_path) as converted:
                self.assertEqual(converted.format, "WEBP")

    def test_invalid_files_handling(self) -> None:
        """Test non-existent file, corrupted image, unsupported format, and invalid quality."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"

            # 1. Non-existent file
            missing = root / "does_not_exist.png"
            res_missing = convert_image(missing, output, 80)
            self.assertEqual(res_missing.status, "Failed")
            self.assertIn("no longer exists", res_missing.error)

            # 2. Unsupported extension
            text_file = root / "notes.txt"
            text_file.write_text("hello")
            res_unsupported = convert_image(text_file, output, 80)
            self.assertEqual(res_unsupported.status, "Failed")
            self.assertIn("Unsupported", res_unsupported.error)

            # 3. Corrupted image
            corrupt = root / "corrupt.png"
            corrupt.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"garbage" * 20)
            res_corrupt = convert_image(corrupt, output, 80)
            self.assertEqual(res_corrupt.status, "Failed")

            # 4. Invalid quality
            valid_img = root / "valid.jpg"
            Image.new("RGB", (10, 10)).save(valid_img)
            res_q_low = convert_image(valid_img, output, 0)
            self.assertEqual(res_q_low.status, "Failed")
            res_q_high = convert_image(valid_img, output, 101)
            self.assertEqual(res_q_high.status, "Failed")

    def test_batch_resilience_one_failure_does_not_stop_batch(self) -> None:
        """Batch processing continues even when an intermediate file fails."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"

            good1 = root / "good1.png"
            bad = root / "corrupted.jpg"
            good2 = root / "good2.png"

            Image.new("RGB", (16, 16), "red").save(good1)
            bad.write_bytes(b"not an image")
            Image.new("RGB", (16, 16), "green").save(good2)

            batch = [good1, bad, good2]
            results = [convert_image(p, output, 80) for p in batch]

            self.assertEqual(results[0].status, "Completed")
            self.assertEqual(results[1].status, "Failed")
            self.assertEqual(results[2].status, "Completed")
            self.assertTrue(results[0].output_path.exists())
            self.assertTrue(results[2].output_path.exists())

    def test_scan_directory_for_images(self) -> None:
        """Verify recursive and non-recursive directory scanning for images."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sub = root / "subdir"
            sub.mkdir()

            (root / "img1.png").write_bytes(b"data")
            (root / "img2.jpg").write_bytes(b"data")
            (root / "doc.txt").write_bytes(b"text")
            (sub / "nested.bmp").write_bytes(b"data")
            (sub / "nested.pdf").write_bytes(b"pdf")

            non_rec = scan_directory_for_images(root, SUPPORTED_EXTENSIONS, recursive=False)
            self.assertEqual(len(non_rec), 2)
            self.assertEqual({p.name for p in non_rec}, {"img1.png", "img2.jpg"})

            rec = scan_directory_for_images(root, SUPPORTED_EXTENSIONS, recursive=True)
            self.assertEqual(len(rec), 3)
            self.assertEqual({p.name for p in rec}, {"img1.png", "img2.jpg", "nested.bmp"})

    def test_convert_image_in_source_directory(self) -> None:
        """Verify converting directly into the image's source parent folder."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "picture.jpg"
            Image.new("RGB", (20, 20), "purple").save(source)

            res = convert_image(source, source.parent, 80)
            self.assertEqual(res.status, "Completed")
            self.assertEqual(res.output_path, root / "picture.webp")
            self.assertTrue(res.output_path.exists())

    def test_convert_image_resizing_max_dimension(self) -> None:
        """Verify proportional downscaling when max_width / max_height is specified."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large.jpg"
            # 2000 x 1000 (aspect 2:1)
            Image.new("RGB", (2000, 1000), "blue").save(source)

            res = convert_image(source, root / "out", 80, max_width=1000, max_height=1000)
            self.assertEqual(res.status, "Completed")
            self.assertEqual(res.width, 1000)
            self.assertEqual(res.height, 500)
            with Image.open(res.output_path) as converted:
                self.assertEqual(converted.size, (1000, 500))

    def test_convert_image_resizing_scale_percent(self) -> None:
        """Verify scale percentage resizing."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.png"
            Image.new("RGB", (400, 200), "green").save(source)

            res = convert_image(source, root / "out", 80, scale_percent=50)
            self.assertEqual(res.status, "Completed")
            self.assertEqual(res.width, 200)
            self.assertEqual(res.height, 100)
            with Image.open(res.output_path) as converted:
                self.assertEqual(converted.size, (200, 100))

    def test_export_results_to_csv(self) -> None:
        """Verify CSV export contains correct headers and records."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jpg"
            Image.new("RGB", (100, 50), "red").save(source)
            res = convert_image(source, root / "out", 80)

            csv_path = root / "report.csv"
            export_results_to_csv([res], csv_path)

            self.assertTrue(csv_path.exists())
            content = csv_path.read_text(encoding="utf-8")
            self.assertIn("Filename,Status,Original Size", content)
            self.assertIn("test.jpg,Completed", content)

    def test_convert_to_avif_format(self) -> None:
        """Verify native AVIF conversion produces a valid AVIF output file."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.jpg"
            Image.new("RGB", (120, 80), "purple").save(source)

            res = convert_image(source, root / "out", quality=75, target_format="AVIF")
            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertTrue(res.output_path.name.endswith(".avif"))
            self.assertTrue(res.output_path.exists())

            with Image.open(res.output_path) as converted:
                self.assertEqual(converted.format, "AVIF")
                self.assertEqual(converted.size, (120, 80))

    def test_apply_image_transformations_rotation(self) -> None:
        """Verify 90, 180, and 270 degree image rotations."""
        base = Image.new("RGB", (200, 100), "red")
        rot90 = apply_image_transformations(base, rotate_angle=90)
        self.assertEqual(rot90.size, (100, 200))

        rot180 = apply_image_transformations(base, rotate_angle=180)
        self.assertEqual(rot180.size, (200, 100))

        rot270 = apply_image_transformations(base, rotate_angle=270)
        self.assertEqual(rot270.size, (100, 200))

    def test_apply_image_transformations_flip(self) -> None:
        """Verify horizontal and vertical flipping."""
        img = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
        img.putpixel((0, 0), (255, 255, 255, 255))

        flipped_h = apply_image_transformations(img, flip_h=True)
        self.assertEqual(flipped_h.getpixel((9, 0)), (255, 255, 255, 255))

        flipped_v = apply_image_transformations(img, flip_v=True)
        self.assertEqual(flipped_v.getpixel((0, 9)), (255, 255, 255, 255))

    def test_apply_image_transformations_aspect_ratio_crop(self) -> None:
        """Verify aspect ratio center cropping for 1:1, 16:9, 4:3."""
        wide = Image.new("RGB", (1000, 500), "cyan")  # 2:1
        square = apply_image_transformations(wide, aspect_ratio="1:1")
        self.assertEqual(square.size, (500, 500))

        tall = Image.new("RGB", (400, 800), "cyan")  # 1:2
        crop_4_3 = apply_image_transformations(tall, aspect_ratio="4:3")
        # 4:3 with width 400 -> height 300
        self.assertEqual(crop_4_3.size, (400, 300))

    def test_apply_image_transformations_rounded_corners(self) -> None:
        """Verify rounded corners produce transparent outer pixels."""
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        rounded = apply_image_transformations(img, corner_radius=25)
        self.assertEqual(rounded.mode, "RGBA")
        # Top-left corner (0,0) should be transparent alpha = 0
        self.assertEqual(rounded.getpixel((0, 0))[3], 0)
        # Center should be fully opaque alpha = 255
        self.assertEqual(rounded.getpixel((50, 50))[3], 255)

    def test_apply_image_transformations_grayscale(self) -> None:
        """Verify grayscale conversion transforms color image to monochrome."""
        img = Image.new("RGB", (50, 50), (255, 0, 0))
        gray = apply_image_transformations(img, grayscale=True)
        pixel = gray.getpixel((0, 0))
        # In RGB mode monochrome, R == G == B
        self.assertEqual(pixel[0], pixel[1])
        self.assertEqual(pixel[1], pixel[2])

    def test_batch_renaming_prefix_suffix_slugify(self) -> None:
        """Verify convert_image respects prefix, suffix, and slugify options."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Summer Vacation 2026!.png"
            Image.new("RGB", (40, 40), "yellow").save(source)

            res = convert_image(
                source,
                root / "out",
                quality=80,
                filename_prefix="thumb_",
                filename_suffix="_web",
                slugify_names=True,
            )
            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertEqual(res.output_path.name, "thumb_summer-vacation-2026_web.webp")


if __name__ == "__main__":
    unittest.main()
