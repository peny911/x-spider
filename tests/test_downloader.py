import unittest
from pathlib import Path

from x_spider.downloader import (
    build_best_image_urls,
    build_local_path,
    extension_from_url_or_content_type,
    is_video_mp4_url,
    parse_hls_segments,
    parse_hls_variants,
    video_candidate_score,
    video_size_from_url,
    VideoCandidate,
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

    def test_build_local_path_allows_nested_scope_parts(self) -> None:
        path = build_local_path(
            Path(".data/downloads"),
            "mentions",
            "authorA/authorB_authorC",
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
            ".data/downloads/mentions/authorA/authorB_authorC/images/"
            "20260608_123_publisher_media_abc_orig.jpg",
        )

    def test_build_local_path_omits_empty_scope_name(self) -> None:
        path = build_local_path(
            Path(".data/downloads"),
            "users",
            "authorA",
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
            ".data/downloads/users/authorA/images/20260608_123_publisher_media_abc_orig.jpg",
        )

    def test_video_size_from_url_reads_dimensions(self) -> None:
        self.assertEqual(
            video_size_from_url(
                "https://video.twimg.com/ext_tw_video/1/pu/vid/avc1/1280x720/file.mp4"
            ),
            (1280, 720),
        )
        self.assertEqual(
            video_size_from_url(
                "https://video.twimg.com/ext_tw_video/1/pu/vid/avc1/0/0/720x1280/file.mp4"
            ),
            (720, 1280),
        )

    def test_is_video_mp4_url_requires_video_host_and_mp4_path(self) -> None:
        self.assertTrue(
            is_video_mp4_url(
                "https://video.twimg.com/ext_tw_video/1/pu/vid/avc1/1280x720/file.mp4"
            )
        )
        self.assertFalse(is_video_mp4_url("https://video.twimg.com/path/master.m3u8"))
        self.assertFalse(is_video_mp4_url("https://example.com/file.mp4"))

    def test_video_candidate_score_prefers_higher_resolution(self) -> None:
        low = VideoCandidate("low.mp4", width=640, height=360, content_length=10_000)
        high = VideoCandidate("high.mp4", width=1280, height=720, content_length=1_000)

        self.assertGreater(video_candidate_score(high), video_candidate_score(low))

    def test_parse_hls_variants_reads_resolution_and_url(self) -> None:
        variants = parse_hls_variants(
            "https://video.twimg.com/master.m3u8",
            "\n".join(
                [
                    "#EXTM3U",
                    '#EXT-X-STREAM-INF:BANDWIDTH=832000,RESOLUTION=480x852',
                    "480x852/playlist.m3u8",
                    '#EXT-X-STREAM-INF:BANDWIDTH=2176000,RESOLUTION=720x1280',
                    "720x1280/playlist.m3u8",
                ]
            ),
        )

        self.assertEqual(len(variants), 2)
        self.assertEqual(variants[1].url, "https://video.twimg.com/720x1280/playlist.m3u8")
        self.assertEqual(variants[1].bandwidth, 2176000)
        self.assertEqual((variants[1].width, variants[1].height), (720, 1280))

    def test_parse_hls_segments_includes_map_before_segments(self) -> None:
        segments = parse_hls_segments(
            "https://video.twimg.com/720x1280/playlist.m3u8",
            "\n".join(
                [
                    "#EXTM3U",
                    '#EXT-X-MAP:URI="init.mp4"',
                    "#EXTINF:1.000,",
                    "seg-1.m4s",
                    "#EXTINF:1.000,",
                    "seg-2.m4s",
                ]
            ),
        )

        self.assertEqual(
            segments,
            [
                "https://video.twimg.com/720x1280/init.mp4",
                "https://video.twimg.com/720x1280/seg-1.m4s",
                "https://video.twimg.com/720x1280/seg-2.m4s",
            ],
        )


if __name__ == "__main__":
    unittest.main()
