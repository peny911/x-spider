import unittest

from x_spider.extractor import (
    extract_handle_from_url,
    extract_tweet_id_from_url,
    parse_extracted_articles,
)


class ExtractorTests(unittest.TestCase):
    def test_extract_tweet_id_from_url(self) -> None:
        self.assertEqual(
            extract_tweet_id_from_url("https://x.com/author/status/1234567890/photo/1"),
            "1234567890",
        )

    def test_extract_handle_from_url(self) -> None:
        self.assertEqual(extract_handle_from_url("https://x.com/author/status/1234567890"), "author")

    def test_parse_extracted_articles_keeps_unique_tweets_with_images(self) -> None:
        raw = [
            {
                "statusUrl": "https://x.com/author/status/123",
                "authorHandle": "author",
                "text": "hello @target",
                "publishedAt": "2026-06-08T01:02:03.000Z",
                "imageUrls": [
                    "https://pbs.twimg.com/media/abc?format=jpg&name=small",
                    "https://example.com/not-image.jpg",
                ],
            },
            {
                "statusUrl": "https://x.com/author/status/123",
                "authorHandle": "author",
                "text": "duplicate",
                "imageUrls": ["https://pbs.twimg.com/media/abc?format=jpg&name=small"],
            },
        ]

        tweets = parse_extracted_articles(raw)

        self.assertEqual(len(tweets), 1)
        self.assertEqual(tweets[0].tweet_id, "123")
        self.assertEqual(tweets[0].author_handle, "author")
        self.assertEqual(len(tweets[0].media), 1)
        self.assertEqual(tweets[0].media[0].media_identity, "image:pbs.twimg.com/media/abc")

    def test_parse_extracted_articles_keeps_tweets_without_media(self) -> None:
        raw = [
            {
                "statusUrl": "https://x.com/author/status/456",
                "authorHandle": "author",
                "text": "text only",
                "imageUrls": [],
            }
        ]

        tweets = parse_extracted_articles(raw)

        self.assertEqual(len(tweets), 1)
        self.assertEqual(tweets[0].tweet_id, "456")
        self.assertEqual(len(tweets[0].media), 0)

    def test_parse_extracted_articles_keeps_video_marker(self) -> None:
        raw = [
            {
                "statusUrl": "https://x.com/author/status/789",
                "authorHandle": "author",
                "text": "video",
                "imageUrls": [],
                "videoUrls": [
                    "https://x.com/author/status/789",
                    "https://pbs.twimg.com/ext_tw_video_thumb/789/pu/img/abc.jpg",
                ],
            }
        ]

        tweets = parse_extracted_articles(raw)

        self.assertEqual(len(tweets), 1)
        self.assertEqual(len(tweets[0].media), 1)
        self.assertEqual(tweets[0].media[0].media_type, "video")
        self.assertEqual(tweets[0].media[0].source_url, "https://x.com/author/status/789")
        self.assertEqual(tweets[0].media[0].media_identity, "video:789")


if __name__ == "__main__":
    unittest.main()
