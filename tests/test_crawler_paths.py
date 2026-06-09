import unittest

from x_spider.scope import CrawlSpec, download_scope_name


class CrawlerPathTests(unittest.TestCase):
    def test_author_crawl_uses_author_under_users_directory(self) -> None:
        spec = CrawlSpec(
            task_type="user",
            media_type="images",
            publishers=("Yoga_miao",),
        )

        self.assertEqual(download_scope_name(spec), "users/Yoga_miao")

    def test_author_mentions_crawl_uses_model_then_author(self) -> None:
        spec = CrawlSpec(
            task_type="user",
            media_type="images",
            publishers=("IES_anh",),
            mentions=("Yoga_miao",),
        )

        self.assertEqual(download_scope_name(spec), "users/Yoga_miao/IES_anh")

    def test_global_mentions_search_uses_model_then_tweet_author_when_known(self) -> None:
        spec = CrawlSpec(
            task_type="search",
            media_type="images",
            mentions=("Yoga_miao",),
        )

        self.assertEqual(download_scope_name(spec, tweet_author="WANIMAL912"), "users/Yoga_miao/WANIMAL912")

    def test_global_mentions_search_uses_model_when_tweet_author_unknown(self) -> None:
        spec = CrawlSpec(
            task_type="search",
            media_type="images",
            mentions=("Yoga_miao",),
        )

        self.assertEqual(download_scope_name(spec), "users/Yoga_miao")


if __name__ == "__main__":
    unittest.main()
