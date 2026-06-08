import unittest
from pathlib import Path

from x_spider.downloader import (
    build_best_image_urls,
    build_local_path,
    extension_from_url_or_content_type,
)


class DownloaderTests(unittest.TestCase):
    def test_build_best_image_urls_prefers_orig(self) -> None:
        candidates = build_best_image_urls("https://pbs.twimg.com/media/abc?format=jpg&name=small")

        self.assertEqual(candidates[0], ("https://pbs.twimg.com/media/abc?format=jpg&name=orig", "orig"))
        self.assertIn(("https://pbs.twimg.com/media/abc?format=jpg&name=small", "small"), candidates)

    def test_extension_uses_format_query_first(self) -> None:
        self.assertEqual(
            extension_from_url_or_content_type(
                "https://pbs.twimg.com/media/abc?format=jpeg&name=orig",
                "image/webp",
            ),
            ".jpg",
        )

    def test_build_local_path_uses_scope_and_publisher(self) -> None:
        path = build_local_path(
            Path(".data/downloads"),
            "mentions",
            "authorA_authorB",
            "images",
            "20260608",
            "123",
            "publisher",
            "media_abc",
            "orig",
            ".jpg",
        )

        self.assertEqual(
            str(path),
            ".data/downloads/mentions/authorA_authorB/images/"
            "20260608_123_publisher_media_abc_orig.jpg",
        )


if __name__ == "__main__":
    unittest.main()
